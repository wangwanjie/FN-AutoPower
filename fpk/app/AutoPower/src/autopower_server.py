#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from .autopower_core import (
        END_MARKER,
        ScheduleValidationError,
        format_trigger,
        next_wake_timestamp,
        render_managed_crontab,
        validate_schedule,
    )
except ImportError:
    from autopower_core import (
        END_MARKER,
        ScheduleValidationError,
        format_trigger,
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


def default_schedules():
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
        {
            "id": "shutdown-daily-2000",
            "enabled": True,
            "operation": "shutdown",
            "days": "daily",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "hour": 20,
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


def install_crontab(schedules):
    existing = read_crontab()
    updated = render_managed_crontab(existing, schedules)
    run_command(["crontab", "-"], input_text=updated)


def write_wake_script(data_dir: Path):
    script = f"""#!/bin/bash
set -euo pipefail
NEXT=$({sys.executable} "{Path(__file__).resolve()}" --data-dir "{data_dir}" --print-next-wake)
if [ -n "$NEXT" ]; then
  echo 0 > "{WAKEALARM_PATH}"
  echo "$NEXT" > "{WAKEALARM_PATH}"
  logger "AutoPower RTC wake set to $(date -d @$NEXT '+%Y-%m-%d %H:%M:%S')"
fi
"""
    WAKE_SCRIPT.write_text(script, encoding="utf-8")
    WAKE_SCRIPT.chmod(0o755)


def install_systemd_service(data_dir: Path):
    write_wake_script(data_dir)
    service = f"""[Unit]
Description=AutoPower RTC wakeup alarm before shutdown
DefaultDependencies=no
Before=shutdown.target

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
    timestamp = next_wake_timestamp(schedules)
    if timestamp is None:
        if WAKEALARM_PATH.exists():
            WAKEALARM_PATH.write_text("0\n", encoding="utf-8")
        return None
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


def public_state(state: AppState):
    data = state.load()
    schedules = []
    for schedule in data["schedules"]:
        enriched = dict(schedule)
        enriched["trigger"] = format_trigger(schedule)
        schedules.append(enriched)
    return {"schedules": schedules, "status": read_status()}


class AutoPowerHandler(SimpleHTTPRequestHandler):
    state = None
    web_dir = DEFAULT_WEB_DIR

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.web_dir), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[autopower] " + fmt % args + "\n")

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(f"invalid json: {exc}", status=400)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self, method):
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            if method == "GET" and parts == ["api", "state"]:
                self.send_json(public_state(self.state))
                return
            if method == "POST" and parts == ["api", "schedules"]:
                self.send_json(create_schedule(self.state, self.read_json()), status=201)
                return
            if method == "PUT" and len(parts) == 3 and parts[:2] == ["api", "schedules"]:
                self.send_json(update_schedule(self.state, parts[2], self.read_json()))
                return
            if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "schedules"]:
                self.send_json(delete_schedule(self.state, parts[2]))
                return
            if method == "POST" and parts == ["api", "apply"]:
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
        if self.path.startswith("/api/"):
            self.handle_api("GET")
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        self.handle_api("POST")

    def do_PUT(self):
        self.handle_api("PUT")

    def do_DELETE(self):
        self.handle_api("DELETE")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AUTOPOWER_PORT", "3868")))
    parser.add_argument("--data-dir", default=os.environ.get("AUTOPOWER_DATA_DIR", str(DEFAULT_DATA_DIR)))
    parser.add_argument("--web-dir", default=os.environ.get("AUTOPOWER_WEB_DIR", str(DEFAULT_WEB_DIR)))
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

    AutoPowerHandler.state = state
    AutoPowerHandler.web_dir = Path(args.web_dir)
    server = ThreadingHTTPServer((args.host, args.port), AutoPowerHandler)
    print(f"AutoPower listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
