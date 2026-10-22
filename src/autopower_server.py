#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import shlex
import sys
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from .autopower_core import (
        ScheduleValidationError,
        format_trigger,
        next_event,
        rtc_offset,
        validate_schedule,
    )
    from .autopower_executor import EXECUTOR_VERSION
except ImportError:
    from autopower_core import (
        ScheduleValidationError,
        format_trigger,
        next_event,
        rtc_offset,
        validate_schedule,
    )
    from autopower_executor import EXECUTOR_VERSION


APP_NAME = "autopower"
DEFAULT_DATA_DIR = Path("/var/packages/autopower/var")
DEFAULT_WEB_DIR = Path(__file__).resolve().parents[1] / "web"
# 执行器（root）的安装位置与状态文件，由 autopower_executor.py --install 写入
EXECUTOR_STATUS_PATH = Path("/var/lib/autopower/status.json")
INSTALLED_EXECUTOR = Path("/usr/local/lib/autopower/autopower_executor.py")
# 执行器由 cron 每分钟运行一次；超过该时长没有运行记录视为异常
EXECUTOR_STALE_SECONDS = 180
RTC_WAKEALARM_PATH = Path("/sys/class/rtc/rtc0/wakealarm")
RTC_SINCE_EPOCH_PATH = Path("/sys/class/rtc/rtc0/since_epoch")
# 应用以包用户运行，不写入任何系统文件；增删改计划只更新 schedules.json，
# 执行器每分钟读取一次，因此计划最迟一分钟后生效。
# ThreadingHTTPServer 并发处理请求：计划文件的读-改-写必须串行，
# 否则两个并发修改会互相覆盖。
STATE_LOCK = threading.RLock()


def default_schedules():
    # 默认只提供一条开机示例计划。绝不能默认带关机计划：用户没有主动
    # 配置过关机时，执行器按默认计划关机会造成机器"莫名其妙关机"。
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


def read_sysfs_int(path: Path):
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_rtc(system_epoch=None):
    """读取 RTC 闹钟，并换算成真实时刻（系统时钟的 Unix 时间戳）。

    wakealarm / since_epoch 都是内核把 RTC 寄存器当作 UTC 解释的秒数。RTC 走本地时间时
    两者都带着同样的时区偏差，减去偏差后才是用户在计划里设置的时刻。
    """
    system_epoch = int(dt.datetime.now().timestamp()) if system_epoch is None else system_epoch
    rtc_epoch = read_sysfs_int(RTC_SINCE_EPOCH_PATH)
    offset = rtc_offset(rtc_epoch, system_epoch) if rtc_epoch is not None else 0
    alarm = read_sysfs_int(RTC_WAKEALARM_PATH)
    return {
        "available": rtc_epoch is not None,
        "offset": offset,
        "wake": alarm - offset if alarm else None,
    }


def executor_script_path():
    """包内执行器脚本的路径，用于生成部署命令。优先使用不随存储卷变化的 /var/apps 软链路径。"""
    app_dest = os.environ.get("TRIM_APPDEST")
    if app_dest:
        return Path(app_dest) / "AutoPower" / "src" / "autopower_executor.py"
    return Path(__file__).resolve().parent / "autopower_executor.py"


def deploy_command(data_dir: Path):
    return f"sudo python3 -I {shlex.quote(str(executor_script_path()))} --install {shlex.quote(str(data_dir))}"


def uninstall_command():
    return f"sudo python3 -I {shlex.quote(str(INSTALLED_EXECUTOR))} --uninstall"


def executor_state(data_dir: Path, now=None):
    """执行器部署状态：missing 未部署、outdated 版本过旧、error 运行异常、ok 正常。"""
    now = now or dt.datetime.now().astimezone()
    result = {
        "expectedVersion": EXECUTOR_VERSION,
        "deployCommand": deploy_command(data_dir),
        "uninstallCommand": uninstall_command(),
        "rtc": read_rtc(),
    }
    try:
        status = json.loads(EXECUTOR_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = None
    if not isinstance(status, dict) or not INSTALLED_EXECUTOR.exists():
        result["state"] = "missing"
        return result

    result.update({key: status.get(key) for key in ("version", "lastRun", "nextWake", "lastShutdown", "lastError", "dataDir")})
    if status.get("version") != EXECUTOR_VERSION:
        result["state"] = "outdated"
        return result
    if status.get("dataDir") and Path(status["dataDir"]) != Path(data_dir):
        result["state"] = "error"
        result["lastError"] = f"执行器读取的数据目录 {status['dataDir']} 与应用不一致，请重新部署"
        return result
    try:
        last_run = dt.datetime.fromisoformat(status.get("lastRun") or "")
        stale = (now - last_run).total_seconds() > EXECUTOR_STALE_SECONDS
    except (TypeError, ValueError):
        stale = True
    if status.get("lastError"):
        result["state"] = "error"
    elif stale:
        result["state"] = "error"
        result["lastError"] = "执行器超过 3 分钟没有运行，请检查 cron 服务"
    else:
        result["state"] = "ok"
    return result


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
        "executor": executor_state(state.data_dir),
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
                self.send_json(created, status=201)
                return
            if method == "PUT" and len(parts) == 3 and parts[:2] == ["api", "schedules"]:
                updated = update_schedule(self.state, parts[2], self.read_json())
                self.send_json(updated)
                return
            if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "schedules"]:
                deleted = delete_schedule(self.state, parts[2])
                self.send_json(deleted)
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
    return parser.parse_args()


def main():
    args = parse_args()
    state = AppState(Path(args.data_dir))
    AutoPowerHandler.state = state
    AutoPowerHandler.web_dir = Path(args.web_dir)
    AutoPowerHandler.base_path = "/" + args.base_path.strip("/") if args.base_path.strip("/") else ""
    server = ThreadingHTTPServer((args.host, args.port), AutoPowerHandler)
    print(f"AutoPower listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
