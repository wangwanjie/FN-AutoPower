#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from .autopower_core import (
        END_MARKER,
        ScheduleValidationError,
        format_trigger,
        next_event,
        next_wake_timestamp,
        render_managed_crontab,
        validate_schedule,
    )
except ImportError:
    from autopower_core import (
        END_MARKER,
        ScheduleValidationError,
        format_trigger,
        next_event,
        next_wake_timestamp,
        render_managed_crontab,
        validate_schedule,
    )


APP_NAME = "autopower"
DEFAULT_DATA_DIR = Path("/var/packages/autopower/var")
DEFAULT_WEB_DIR = Path(__file__).resolve().parents[1] / "web"
WAKE_SCRIPT = Path("/usr/local/bin/autopower-set-next-wake.sh")
SYSTEMD_SERVICE = Path("/etc/systemd/system/autopower-rtc-wake.service")
WAKEALARM_PATH = Path("/sys/class/rtc/rtc0/wakealarm")
# ThreadingHTTPServer 并发处理请求：计划文件的读-改-写和系统同步必须串行，
# 否则两个并发修改会互相覆盖。
STATE_LOCK = threading.RLock()
# 只在 Linux（fnOS）上真正改写 crontab / RTC / systemd。在 macOS 等开发机上
# 本地调试时，增删计划也会触发同步，没有这个保护会改动开发机的 crontab。
# 设置 AUTOPOWER_DRY_RUN=1 可在 Linux 上同样禁用系统写入。
SYSTEM_WRITES_ENABLED = sys.platform.startswith("linux") and os.environ.get("AUTOPOWER_DRY_RUN") != "1"


def default_schedules():
    # 默认只提供一条开机示例计划。绝不能默认带关机计划：用户没有主动
    # 配置过关机时，应用后 crontab 里出现 poweroff 会造成机器"莫名其妙关机"。
    return [
        {
            "id": "wake-daily-1500",
            "enabled": True,
            "operation": "wake",
            "days": "daily",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "hour": 15,
            "minute": 0,
        },
    ]


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class AppState:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "schedules.json"

    def load(self):
        if not self.path.exists():
            return {"schedules": default_schedules()}
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        schedules = [validate_schedule(schedule) for schedule in data.get("schedules", [])]
        return {"schedules": schedules}

    def save(self, data):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        schedules = [validate_schedule(schedule) for schedule in data.get("schedules", [])]
        payload = {"schedules": schedules}
        temp_path = self.path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.replace(self.path)
        return payload


def create_schedule(state: AppState, payload):
    data = state.load()
    schedule = dict(payload)
    schedule["id"] = schedule.get("id") or str(uuid.uuid4())
    valid = validate_schedule(schedule)
    data["schedules"].append(valid)
    state.save(data)
    return valid


def update_schedule(state: AppState, schedule_id: str, payload):
    data = state.load()
    schedules = data["schedules"]
    for index, current in enumerate(schedules):
        if current["id"] == schedule_id:
            replacement = dict(payload)
            replacement["id"] = schedule_id
            valid = validate_schedule(replacement)
            schedules[index] = valid
            state.save(data)
            return valid
    raise ApiError("schedule not found", status=404)


def delete_schedule(state: AppState, schedule_id: str):
    data = state.load()
    filtered = [schedule for schedule in data["schedules"] if schedule["id"] != schedule_id]
    if len(filtered) == len(data["schedules"]):
        raise ApiError("schedule not found", status=404)
    data["schedules"] = filtered
    state.save(data)
    return {"ok": True}


def run_command(args, input_text=None):
    completed = subprocess.run(
        args,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise ApiError(f"{' '.join(args)} failed: {completed.stderr.strip() or completed.stdout.strip()}", status=500)
    return completed.stdout


def read_crontab():
    completed = subprocess.run(["crontab", "-l"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        return ""
    return completed.stdout


def ensure_system_writes():
    if not SYSTEM_WRITES_ENABLED:
        raise ApiError("当前环境不允许写入系统（仅 fnOS/Linux 可用，或已设置 AUTOPOWER_DRY_RUN=1）", status=500)


def install_crontab(schedules):
    ensure_system_writes()
    existing = read_crontab()
    updated = render_managed_crontab(existing, schedules)
    run_command(["crontab", "-"], input_text=updated)


def write_wake_script(data_dir: Path):
    script = f"""#!/bin/bash
set -euo pipefail
NEXT=$({sys.executable} "{Path(__file__).resolve()}" --data-dir "{data_dir}" --print-next-wake)
if [ -n "$NEXT" ]; then
  # rtcwake 会根据 /etc/adjtime 处理硬件时钟为 localtime 的情况；
  # 直接写 sysfs 则假定 RTC 为 UTC，在 RTC 走本地时间的机器上会差时区。
  if command -v rtcwake >/dev/null 2>&1; then
    rtcwake -m no -t "$NEXT"
  else
    echo 0 > "{WAKEALARM_PATH}"
    echo "$NEXT" > "{WAKEALARM_PATH}"
  fi
  logger "AutoPower RTC wake set to $(date -d @$NEXT '+%Y-%m-%d %H:%M:%S')"
fi
"""
    WAKE_SCRIPT.write_text(script, encoding="utf-8")
    WAKE_SCRIPT.chmod(0o755)


def install_systemd_service(data_dir: Path):
    ensure_system_writes()
    write_wake_script(data_dir)
    # 依赖 systemd 默认依赖（Conflicts=shutdown.target + Before=shutdown.target），
    # 保证关机流程会有序 stop 本服务从而执行 ExecStop 写入 RTC 闹钟。
    # 之前写了 DefaultDependencies=no 却没补 Conflicts=shutdown.target，
    # 导致关机时 ExecStop 根本不运行，唤醒闹钟从未设置。
    service = f"""[Unit]
Description=AutoPower RTC wakeup alarm before shutdown

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStop={WAKE_SCRIPT}

[Install]
WantedBy=multi-user.target
"""
    SYSTEMD_SERVICE.write_text(service, encoding="utf-8")
    run_command(["systemctl", "daemon-reload"])
    run_command(["systemctl", "enable", SYSTEMD_SERVICE.name])
    run_command(["systemctl", "start", SYSTEMD_SERVICE.name])


def write_next_wake(schedules):
    ensure_system_writes()
    timestamp = next_wake_timestamp(schedules)
    if timestamp is None:
        if WAKEALARM_PATH.exists():
            WAKEALARM_PATH.write_text("0\n", encoding="utf-8")
        return None
    rtcwake = shutil.which("rtcwake")
    if rtcwake:
        # rtcwake 依据 /etc/adjtime 兼容硬件时钟为 localtime 的机器
        run_command([rtcwake, "-m", "no", "-t", str(timestamp)])
    else:
        WAKEALARM_PATH.write_text("0\n", encoding="utf-8")
        WAKEALARM_PATH.write_text(f"{timestamp}\n", encoding="utf-8")
    return timestamp


def read_status():
    status = {"rtc": {}, "systemd": "unknown", "crontabManaged": False}
    try:
        rtc = Path("/proc/driver/rtc").read_text(encoding="utf-8", errors="ignore")
        for line in rtc.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                status["rtc"][key.strip()] = value.strip()
    except OSError:
        status["rtcError"] = "unable to read /proc/driver/rtc"

    try:
        status["systemd"] = run_command(["systemctl", "is-enabled", SYSTEMD_SERVICE.name]).strip()
    except (ApiError, OSError):
        status["systemd"] = "disabled"

    try:
        status["crontabManaged"] = END_MARKER in read_crontab()
    except (ApiError, OSError):
        status["crontabManaged"] = False
    return status


def apply_system_state(state: AppState):
    data = state.load()
    schedules = data["schedules"]
    install_crontab(schedules)
    install_systemd_service(state.data_dir)
    wake_timestamp = write_next_wake(schedules)
    return {"ok": True, "nextWake": wake_timestamp, "status": read_status()}


def sync_system_state(state: AppState):
    """计划增删改后立即同步 crontab 与 RTC 闹钟（尽力而为）。

    之前只有点"应用"才会重写 crontab：在界面删除关机计划后，
    crontab 里残留的 poweroff 行仍会继续定时关机。
    """
    warnings = []
    schedules = state.load()["schedules"]
    try:
        install_crontab(schedules)
    except Exception as exc:
        warnings.append(f"crontab sync failed: {exc}")
    try:
        write_next_wake(schedules)
    except Exception as exc:
        warnings.append(f"wakealarm sync failed: {exc}")
    for warning in warnings:
        sys.stderr.write(f"[autopower] {warning}\n")
    return warnings


def restore_system_state(state: AppState):
    """服务启动时重新应用已保存的计划。

    飞牛升级应用时会先执行旧版本的卸载脚本，可能把 crontab 托管区、
    唤醒服务和 RTC 闹钟一并清掉；升级或迁移存储卷后应用路径也可能变化，
    旧唤醒脚本里的绝对路径会失效。启动时按 schedules.json 重新应用一次，
    保证升级后计划照常生效。从未保存过计划（全新安装）时不写入系统。
    """
    if not SYSTEM_WRITES_ENABLED or not state.path.exists():
        return None
    try:
        result = apply_system_state(state)
        sys.stderr.write(f"[autopower] restored system state on start, next wake: {result['nextWake']}\n")
        return result
    except Exception as exc:
        sys.stderr.write(f"[autopower] restore system state failed: {exc}\n")
        return None


def describe_event(event):
    if event is None:
        return None
    local = dt.datetime.fromtimestamp(event["timestamp"]).astimezone()
    return {**event, "localTime": local.strftime("%Y-%m-%d %H:%M"), "timezone": local.strftime("%Z %z").strip()}


def public_state(state: AppState):
    data = state.load()
    schedules = []
    for schedule in data["schedules"]:
        enriched = dict(schedule)
        enriched["trigger"] = format_trigger(schedule)
        schedules.append(enriched)
    return {
        "schedules": schedules,
        "nextEvent": describe_event(next_event(data["schedules"])),
        "status": read_status(),
    }


class AutoPowerHandler(SimpleHTTPRequestHandler):
    state = None
    web_dir = DEFAULT_WEB_DIR
    base_path = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.web_dir), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[autopower] " + fmt % args + "\n")

    def strip_base_path(self):
        """Remove a reverse-proxy mount prefix (e.g. /autopower) so routing and
        static file serving keep working when the proxy does not strip it."""
        prefix = self.base_path
        if not prefix:
            return
        path = self.path
        if path == prefix:
            self.path = "/"
            return
        if path.startswith(prefix + "/"):
            self.path = path[len(prefix):]

    def read_json(self):
        # 只接受 application/json：普通 HTML 表单无法发出该类型，
        # 可以阻止第三方页面借用户的飞牛登录态跨站提交（CSRF）。
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ApiError("content type must be application/json", status=415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError("invalid content length", status=400)
        if length == 0:
            return {}
        if length > 64 * 1024:
            raise ApiError("request body too large", status=413)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(f"invalid json: {exc}", status=400)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self, method):
        if method == "GET":
            self._handle_api(method)
            return
        with STATE_LOCK:
            self._handle_api(method)

    def _handle_api(self, method):
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            if method == "GET" and parts == ["api", "state"]:
                self.send_json(public_state(self.state))
                return
            if method == "POST" and parts == ["api", "schedules"]:
                created = create_schedule(self.state, self.read_json())
                sync_system_state(self.state)
                self.send_json(created, status=201)
                return
            if method == "PUT" and len(parts) == 3 and parts[:2] == ["api", "schedules"]:
                updated = update_schedule(self.state, parts[2], self.read_json())
                sync_system_state(self.state)
                self.send_json(updated)
                return
            if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "schedules"]:
                deleted = delete_schedule(self.state, parts[2])
                sync_system_state(self.state)
                self.send_json(deleted)
                return
            if method == "POST" and parts == ["api", "apply"]:
                self.read_json()
                try:
                    self.send_json(apply_system_state(self.state))
                except Exception as exc:
                    schedules = self.state.load()["schedules"]
                    self.send_json(
                        {
                            "ok": False,
                            "error": str(exc),
                            "nextWake": next_wake_timestamp(schedules),
                            "status": read_status(),
                        }
                    )
                return
            if method == "POST" and parts == ["api", "test-wake"]:
                self.read_json()
                schedules = self.state.load()["schedules"]
                timestamp = next_wake_timestamp(schedules)
                try:
                    written_timestamp = write_next_wake(schedules)
                    self.send_json({"ok": True, "nextWake": written_timestamp, "status": read_status()})
                except Exception as exc:
                    self.send_json({"ok": False, "error": str(exc), "nextWake": timestamp, "status": read_status()})
                return
            raise ApiError("not found", status=404)
        except ScheduleValidationError as exc:
            self.send_json({"error": str(exc)}, status=400)
        except ApiError as exc:
            self.send_json({"error": str(exc)}, status=exc.status)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def do_GET(self):
        self.strip_base_path()
        if self.path.startswith("/api/"):
            self.handle_api("GET")
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        self.strip_base_path()
        self.handle_api("POST")

    def do_PUT(self):
        self.strip_base_path()
        self.handle_api("PUT")

    def do_DELETE(self):
        self.strip_base_path()
        self.handle_api("DELETE")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AUTOPOWER_PORT", "3868")))
    parser.add_argument("--data-dir", default=os.environ.get("AUTOPOWER_DATA_DIR", str(DEFAULT_DATA_DIR)))
    parser.add_argument("--web-dir", default=os.environ.get("AUTOPOWER_WEB_DIR", str(DEFAULT_WEB_DIR)))
    parser.add_argument(
        "--base-path",
        default=os.environ.get("AUTOPOWER_BASE_PATH", ""),
        help="反向代理挂载前缀，例如 /autopower。仅当代理不剥离前缀时才需要设置。",
    )
    parser.add_argument("--print-next-wake", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    state = AppState(Path(args.data_dir))
    if args.print_next_wake:
        timestamp = next_wake_timestamp(state.load()["schedules"], dt.datetime.now().astimezone())
        if timestamp is not None:
            print(timestamp)
        return

    restore_system_state(state)
    AutoPowerHandler.state = state
    AutoPowerHandler.web_dir = Path(args.web_dir)
    AutoPowerHandler.base_path = "/" + args.base_path.strip("/") if args.base_path.strip("/") else ""
    server = ThreadingHTTPServer((args.host, args.port), AutoPowerHandler)
    print(f"AutoPower listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
