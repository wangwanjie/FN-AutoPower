#!/usr/bin/env python3
"""AutoPower root 执行器。

应用本身以包用户运行，只负责编辑计划并写入 schedules.json。真正需要 root 的
动作（按计划关机、写主板 RTC 唤醒闹钟、关机前写入下次开机时间）由本执行器完成。

部署方式：管理员通过 SSH 执行一次
    sudo python3 -I <应用目录>/src/autopower_executor.py --install <数据目录>
安装后本文件与 autopower_core.py 被复制到 root 所有的 INSTALL_DIR，
由 /etc/cron.d/autopower 每分钟以 root 运行 --run。

安全边界：
- 执行器只做两件事：/sbin/poweroff 关机、写 RTC 唤醒闹钟，不执行任何来自配置的命令
- 数据目录只在安装时由管理员指定，写入 root 所有的锚定文件；--run 不接受路径参数
- 只读取数据目录下的 schedules.json（不跟随符号链接、限制大小、逐条校验），
  从不向应用可写的目录写入任何文件；状态写在 root 所有的 STATE_DIR
"""
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from autopower_core import (  # noqa: E402
    BEGIN_MARKER,
    END_MARKER,
    ScheduleValidationError,
    next_wake_timestamp,
    rtc_alarm_value,
    rtc_offset,
    strip_managed_crontab,
    validate_schedule,
)


# 执行器逻辑变化时递增；应用发现已部署版本不一致时提示管理员重新部署
EXECUTOR_VERSION = "1.1.0"

INSTALL_DIR = Path("/usr/local/lib/autopower")
INSTALLED_EXECUTOR = INSTALL_DIR / "autopower_executor.py"
CONFIG_DIR = Path("/etc/autopower")
DATA_DIR_ANCHOR = CONFIG_DIR / "data-dir"
STATE_DIR = Path("/var/lib/autopower")
STATUS_PATH = STATE_DIR / "status.json"
CRON_FILE = Path("/etc/cron.d/autopower")
SYSTEMD_SERVICE = Path("/etc/systemd/system/autopower-rtc-wake.service")
WAKEALARM_PATH = Path("/sys/class/rtc/rtc0/wakealarm")
RTC_SINCE_EPOCH_PATH = Path("/sys/class/rtc/rtc0/since_epoch")
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
POWEROFF = "/sbin/poweroff"
# 找不到当前解释器的绝对路径时使用的默认值
DEFAULT_PYTHON = "/usr/bin/python3"
SCHEDULES_MAX_BYTES = 256 * 1024
# status.json 中保留的最近关机记录条数，供应用界面展示
HISTORY_LIMIT = 10
# 1.1.x 以 root 运行时安装的旧唤醒脚本，部署执行器时一并清理
LEGACY_WAKE_SCRIPT = Path("/usr/local/bin/autopower-set-next-wake.sh")


class ExecutorError(Exception):
    pass


class DataDirMissing(ExecutorError):
    """数据目录不存在：应用已被卸载，或开机时存储卷尚未挂载。"""


def log(message):
    sys.stderr.write(f"[autopower-executor] {message}\n")


def now_local():
    return dt.datetime.now().astimezone()


def write_atomic(path: Path, content: str, mode: int):
    """同目录临时文件 + rename，读取方永远只看到完整文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except BaseException:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise


def read_data_dir() -> Path:
    try:
        raw = DATA_DIR_ANCHOR.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ExecutorError(f"未部署：无法读取 {DATA_DIR_ANCHOR}") from exc
    return validate_data_dir(raw)


def validate_data_dir(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or str(path) == "/":
        raise ExecutorError(f"数据目录无效：{raw}")
    if not path.is_dir():
        raise DataDirMissing(f"数据目录不存在：{raw}")
    return path


def load_schedules(data_dir: Path):
    """读取应用写入的计划。文件不存在视为没有计划；单条非法的计划被跳过。"""
    path = data_dir / "schedules.json"
    try:
        # O_NOFOLLOW：拒绝符号链接，避免应用用户把它指向 root 才能读的文件
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ExecutorError(f"无法读取 {path}: {exc}") from exc
    with os.fdopen(fd, "rb") as handle:
        raw = handle.read(SCHEDULES_MAX_BYTES + 1)
    if len(raw) > SCHEDULES_MAX_BYTES:
        raise ExecutorError("schedules.json 过大")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutorError(f"schedules.json 解析失败: {exc}") from exc
    schedules = []
    for item in data.get("schedules", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        try:
            schedules.append(validate_schedule(item))
        except ScheduleValidationError as exc:
            log(f"跳过无效计划: {exc}")
    return schedules


def load_status():
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_status(status):
    status["version"] = EXECUTOR_VERSION
    write_atomic(STATUS_PATH, json.dumps(status, ensure_ascii=False, indent=2) + "\n", 0o644)


def read_boot_id():
    try:
        return BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_rtc_offset():
    """测量 RTC 与系统时钟的实际偏差（秒）。

    since_epoch 是内核把 RTC 寄存器当作 UTC 解释得到的秒数：RTC 走 UTC 时偏差为 0，
    走本地时间（如 BIOS 显示北京时间）时偏差为时区秒数。直接测量比依赖 /etc/adjtime 的
    声明更可靠，读不到时按 RTC 走 UTC 处理。
    """
    try:
        rtc_epoch = int(RTC_SINCE_EPOCH_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    return rtc_offset(rtc_epoch, int(time.time()))


def read_rtc_alarm():
    """当前 RTC 闹钟的原始读数（RTC 纪元秒），未设置或读不到时返回 None。"""
    try:
        raw = WAKEALARM_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value or None


def rtc_alarm_matches(timestamp):
    """RTC 里的闹钟是否就是期望值：其他程序（如 BIOS、系统自带的定时开机）可能改写或清除它。"""
    current = read_rtc_alarm()
    if timestamp is None:
        return current is None
    # 闹钟已经过去时内核会把它当作已触发，此时 sync_wake 会按新的下次开机时间重写
    return current == rtc_alarm_value(timestamp, read_rtc_offset())


def write_rtc_wake(timestamp):
    """写 RTC 唤醒闹钟并返回补偿的 RTC 偏差；timestamp 为 None 时清除闹钟。"""
    if timestamp is None:
        if WAKEALARM_PATH.exists():
            WAKEALARM_PATH.write_text("0\n", encoding="utf-8")
        return 0
    # wakealarm 按 RTC 走 UTC 换算，RTC 与系统时钟存在时区偏差时在这里补偿，
    # 用户始终按系统（北京）时间设置计划
    offset = read_rtc_offset()
    # 已有闹钟时直接写新值会返回 EBUSY，先清零
    WAKEALARM_PATH.write_text("0\n", encoding="utf-8")
    WAKEALARM_PATH.write_text(f"{rtc_alarm_value(timestamp, offset)}\n", encoding="utf-8")
    return offset


def shutdown_due(schedules, now):
    """当前这一分钟是否命中某条启用的关机计划，命中时返回计划 id。"""
    for schedule in schedules:
        if not schedule["enabled"] or schedule["operation"] != "shutdown":
            continue
        if schedule["hour"] == now.hour and schedule["minute"] == now.minute and now.weekday() in schedule["weekdays"]:
            return schedule["id"]
    return None


def sync_wake(schedules, status, now=None, force=False):
    """下次开机时间变化、重启过、RTC 闹钟被改动或强制时才重写，避免每分钟都写闹钟。

    now 为 None 时按系统时区计算（正确处理夏令时），测试中传入带时区的固定时刻。
    """
    timestamp = next_wake_timestamp(schedules, now)
    boot_id = read_boot_id()
    changed = status.get("nextWake") != timestamp or status.get("bootId") != boot_id
    if force or changed or not rtc_alarm_matches(timestamp):
        status["rtcOffset"] = write_rtc_wake(timestamp)
        status["nextWake"] = timestamp
        status["bootId"] = boot_id
        status["wakeWrittenAt"] = (now or now_local()).isoformat(timespec="seconds")
    return timestamp


def run_once(now=None):
    """cron 每分钟调用：同步 RTC 唤醒，命中关机计划时关机。"""
    clock = now or now_local()
    status = load_status()
    status["lastRun"] = clock.isoformat(timespec="seconds")
    try:
        data_dir = read_data_dir()
        schedules = load_schedules(data_dir)
        sync_wake(schedules, status, now)
        minute_key = clock.strftime("%Y-%m-%dT%H:%M")
        schedule_id = shutdown_due(schedules, clock)
        # 同一分钟只关机一次：开机恰好落在关机那一分钟时不会再次关机
        if schedule_id and status.get("lastShutdown") != minute_key:
            status["lastShutdown"] = minute_key
            status["lastShutdownSchedule"] = schedule_id
            history = status.get("history") if isinstance(status.get("history"), list) else []
            history.insert(0, {"time": clock.isoformat(timespec="seconds"), "schedule": schedule_id})
            status["history"] = history[:HISTORY_LIMIT]
            status["lastError"] = None
            save_status(status)
            log(f"按计划 {schedule_id} 关机")
            subprocess.run([POWEROFF], check=False)
            return 0
        status["lastError"] = None
        save_status(status)
        return 0
    except DataDirMissing as exc:
        # 应用卸载后不再按旧计划唤醒机器；存储卷只是晚挂载时，下一分钟会重新写入
        if status.get("nextWake") is not None:
            write_rtc_wake(None)
            status["nextWake"] = None
        status["lastError"] = str(exc)
        save_status(status)
        return 1
    except Exception as exc:
        status["lastError"] = str(exc)
        save_status(status)
        log(str(exc))
        return 1


def set_wake_before_shutdown():
    """systemd 关机钩子：关机（包括手动关机）前写入下一次开机时间。"""
    status = load_status()
    try:
        schedules = load_schedules(read_data_dir())
        timestamp = sync_wake(schedules, status, force=True)
        save_status(status)
        log(f"关机前写入下次开机时间: {timestamp}")
        return 0
    except Exception as exc:
        status["lastError"] = str(exc)
        save_status(status)
        log(str(exc))
        return 1


def require_root():
    if os.geteuid() != 0:
        raise ExecutorError("需要 root 权限，请用 sudo 执行")


def remove_legacy_crontab():
    """清理 1.1.x 写入 root crontab 的 AUTOPOWER 托管区（现在由 /etc/cron.d 负责）。"""
    if not shutil.which("crontab"):
        return
    current = subprocess.run(["crontab", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if current.returncode != 0 or BEGIN_MARKER not in current.stdout:
        return
    remaining = strip_managed_crontab(current.stdout)
    if remaining:
        subprocess.run(["crontab", "-"], input=remaining + "\n", text=True, check=True)
    else:
        subprocess.run(["crontab", "-r"], check=False)
    log(f"已清理 root crontab 中的旧 {BEGIN_MARKER} / {END_MARKER} 托管区")


def systemctl(*args):
    subprocess.run(["systemctl", *args], check=True)


def python_path():
    """cron 与 systemd 使用的解释器：优先用执行部署命令时的 python3，保证路径真实存在。"""
    executable = sys.executable
    if executable and os.path.isabs(executable) and os.access(executable, os.X_OK):
        return executable
    return DEFAULT_PYTHON


def install(raw_data_dir):
    require_root()
    data_dir = validate_data_dir(raw_data_dir)
    source_dir = Path(__file__).resolve().parent

    # 复制到 root 所有的目录：应用目录对包用户可写，cron 绝不能直接运行那里的代码
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(INSTALL_DIR, 0o755)
    for name in ("autopower_core.py", "autopower_executor.py"):
        write_atomic(INSTALL_DIR / name, (source_dir / name).read_text(encoding="utf-8"), 0o644)

    write_atomic(DATA_DIR_ANCHOR, f"{data_dir}\n", 0o644)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o755)

    executor = f"{shlex.quote(python_path())} -I {INSTALLED_EXECUTOR}"
    write_atomic(
        CRON_FILE,
        "# AutoPower：每分钟检查关机计划并同步 RTC 唤醒闹钟\n"
        "SHELL=/bin/sh\n"
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        f"* * * * * root {executor} --run >/dev/null 2>&1\n",
        0o644,
    )

    # 依赖 systemd 默认依赖（Conflicts/Before=shutdown.target），关机时会 stop 本服务，
    # 从而执行 ExecStop 写入下次开机时间
    write_atomic(
        SYSTEMD_SERVICE,
        "[Unit]\n"
        "Description=AutoPower RTC wakeup alarm before shutdown\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        f"ExecStop={executor} --set-wake\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n",
        0o644,
    )
    if LEGACY_WAKE_SCRIPT.exists():
        LEGACY_WAKE_SCRIPT.unlink()
    remove_legacy_crontab()
    systemctl("daemon-reload")
    systemctl("enable", SYSTEMD_SERVICE.name)
    # restart：从 1.1.x 迁移时服务已在运行，需要换成新的 ExecStop
    systemctl("restart", SYSTEMD_SERVICE.name)

    status = load_status()
    status["installedAt"] = status["lastRun"] = now_local().isoformat(timespec="seconds")
    status["dataDir"] = str(data_dir)
    timestamp = sync_wake(load_schedules(data_dir), status, force=True)
    status["lastError"] = None
    save_status(status)
    print(f"AutoPower 执行器 {EXECUTOR_VERSION} 部署完成")
    print(f"数据目录: {data_dir}")
    print(f"下次开机: {dt.datetime.fromtimestamp(timestamp).astimezone():%Y-%m-%d %H:%M}" if timestamp else "下次开机: 未启用开机计划")
    return 0


def uninstall():
    require_root()
    subprocess.run(["systemctl", "disable", "--now", SYSTEMD_SERVICE.name], check=False)
    for path in (CRON_FILE, SYSTEMD_SERVICE, DATA_DIR_ANCHOR, STATUS_PATH, LEGACY_WAKE_SCRIPT,
                 INSTALL_DIR / "autopower_core.py", INSTALL_DIR / "autopower_executor.py"):
        if path.exists():
            path.unlink()
    for directory in (INSTALL_DIR, CONFIG_DIR, STATE_DIR):
        shutil.rmtree(directory, ignore_errors=True)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    remove_legacy_crontab()
    write_rtc_wake(None)
    print("AutoPower 执行器已卸载，RTC 唤醒闹钟已清除")
    return 0


def usage():
    sys.stderr.write(
        "用法:\n"
        "  sudo python3 -I autopower_executor.py --install <数据目录>\n"
        "  sudo python3 -I /usr/local/lib/autopower/autopower_executor.py --uninstall\n"
        "  autopower_executor.py --version\n"
    )
    return 2


def main(argv):
    try:
        if argv == ["--version"]:
            print(EXECUTOR_VERSION)
            return 0
        if argv == ["--run"]:
            require_root()
            return run_once()
        if argv == ["--set-wake"]:
            require_root()
            return set_wake_before_shutdown()
        if len(argv) == 2 and argv[0] == "--install":
            return install(argv[1])
        if argv == ["--uninstall"]:
            return uninstall()
        return usage()
    except (ExecutorError, subprocess.CalledProcessError, OSError) as exc:
        sys.stderr.write(f"失败: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
