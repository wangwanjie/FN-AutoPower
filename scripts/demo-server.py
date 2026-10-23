#!/usr/bin/env python3
"""启动带示例数据的演示服务，用于本地预览界面和生成 README 截图。

所有数据写在临时目录：示例计划、已部署且运行正常的执行器状态、走北京时间的 RTC。
不读写任何系统文件。

用法：python3 scripts/demo-server.py [--port 3869]
"""
import argparse
import datetime as dt
import json
import sys
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import autopower_server  # noqa: E402
from src.autopower_core import next_wake_timestamp  # noqa: E402
from src.autopower_executor import EXECUTOR_VERSION  # noqa: E402


SCHEDULES = [
    {"id": "wake-weekday", "enabled": True, "operation": "wake", "days": "weekday", "hour": 8, "minute": 30, "note": "工作日上班前开机"},
    {"id": "off-weekday", "enabled": True, "operation": "shutdown", "days": "weekday", "hour": 23, "minute": 0, "note": "工作日夜间关机"},
    {"id": "wake-weekend", "enabled": True, "operation": "wake", "days": "holiday", "hour": 10, "minute": 0, "note": "周末晚点开机"},
    {"id": "off-weekend", "enabled": True, "operation": "shutdown", "days": "holiday", "hour": 1, "minute": 30, "note": "周末熬夜后关机"},
    {"id": "reboot-weekly", "enabled": True, "operation": "reboot", "days": "custom", "weekdays": [0], "hour": 4, "minute": 0, "note": "每周一凌晨重启"},
    {"id": "backup", "enabled": False, "operation": "wake", "days": "custom", "weekdays": [2], "hour": 3, "minute": 0, "note": "每周三凌晨备份"},
]

# 演示 RTC 走北京时间：读数比系统时钟快 8 小时，界面会显示“已自动补偿”
RTC_OFFSET = 8 * 3600


def prepare(root: Path):
    data_dir = root / "data"
    data_dir.mkdir()
    (data_dir / "schedules.json").write_text(json.dumps({"schedules": SCHEDULES}, ensure_ascii=False))

    now = dt.datetime.now().astimezone()
    next_wake = next_wake_timestamp(SCHEDULES)
    history = [
        {"time": (now.replace(hour=23, minute=0, second=0) - dt.timedelta(days=day)).isoformat(timespec="seconds"), "schedule": "off-weekday"}
        for day in range(1, 4)
    ]
    installed = root / "autopower_executor.py"
    installed.write_text("")
    status_path = root / "status.json"
    status_path.write_text(json.dumps({
        "version": EXECUTOR_VERSION,
        "lastRun": now.isoformat(timespec="seconds"),
        "nextWake": next_wake,
        "dataDir": str(data_dir),
        "lastError": None,
        "history": history,
    }))
    since_epoch = root / "since_epoch"
    since_epoch.write_text(f"{int(now.timestamp()) + RTC_OFFSET}\n")
    wakealarm = root / "wakealarm"
    wakealarm.write_text(f"{next_wake + RTC_OFFSET}\n")

    autopower_server.EXECUTOR_STATUS_PATH = status_path
    autopower_server.INSTALLED_EXECUTOR = installed
    autopower_server.RTC_SINCE_EPOCH_PATH = since_epoch
    autopower_server.RTC_WAKEALARM_PATH = wakealarm

    # 部署命令展示 fnOS 上的真实路径，而不是本机临时目录
    original_state = autopower_server.executor_state

    def executor_state(data_dir, now=None):
        result = original_state(data_dir, now)
        result["deployCommand"] = "sudo python3 -I /var/apps/autopower/target/AutoPower/src/autopower_executor.py --install /vol1/@appdata/autopower"
        result["uninstallCommand"] = "sudo python3 -I /usr/local/lib/autopower/autopower_executor.py --uninstall"
        return result

    autopower_server.executor_state = executor_state
    return data_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3869)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="autopower-demo-") as temp:
        data_dir = prepare(Path(temp))
        autopower_server.AutoPowerHandler.state = autopower_server.AppState(data_dir)
        autopower_server.AutoPowerHandler.web_dir = ROOT / "web"
        server = ThreadingHTTPServer((args.host, args.port), autopower_server.AutoPowerHandler)
        print(f"AutoPower demo listening on http://{args.host}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
