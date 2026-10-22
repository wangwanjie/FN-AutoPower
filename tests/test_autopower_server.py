import io
import json
import tempfile
import unittest
from pathlib import Path

from src.autopower_server import ApiError, AppState, AutoPowerHandler, create_schedule, update_schedule


class _StubHandler:
    """Minimal stand-in to exercise path normalization without opening a socket."""

    strip_base_path = AutoPowerHandler.strip_base_path

    def __init__(self, base_path, path):
        self.base_path = base_path
        self.path = path


class AutoPowerServerTests(unittest.TestCase):
    def test_state_loads_default_schedules_when_file_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = AppState(Path(temp_dir))

            data = state.load()

            # 默认只允许有开机计划，绝不能内置关机计划（会造成未配置也定时关机）
            self.assertEqual(len(data["schedules"]), 1)
            self.assertEqual(data["schedules"][0]["operation"], "wake")
            self.assertEqual(data["schedules"][0]["hour"], 15)
            self.assertFalse(any(s["operation"] == "shutdown" for s in data["schedules"]))

    def test_create_schedule_persists_valid_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = AppState(Path(temp_dir))

            created = create_schedule(
                state,
                {"enabled": True, "operation": "shutdown", "days": "custom", "weekdays": [4], "hour": 14, "minute": 30},
            )
            data = json.loads((Path(temp_dir) / "schedules.json").read_text())

            self.assertEqual(created["operation"], "shutdown")
            self.assertEqual(data["schedules"][-1]["hour"], 14)
            self.assertTrue(data["schedules"][-1]["id"])

    def test_update_schedule_replaces_existing_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = AppState(Path(temp_dir))
            existing = create_schedule(state, {"enabled": True, "operation": "wake", "days": "daily", "hour": 9, "minute": 0})

            updated = update_schedule(state, existing["id"], {"enabled": False, "operation": "wake", "days": "daily", "hour": 10, "minute": 15})

            self.assertFalse(updated["enabled"])
            self.assertEqual(updated["hour"], 10)
            self.assertEqual(updated["minute"], 15)


class BasePathTests(unittest.TestCase):
    def test_no_base_path_leaves_path_unchanged(self):
        handler = _StubHandler("", "/api/state")
        handler.strip_base_path()
        self.assertEqual(handler.path, "/api/state")

    def test_strips_prefix_from_api_path(self):
        handler = _StubHandler("/autopower", "/autopower/api/state")
        handler.strip_base_path()
        self.assertEqual(handler.path, "/api/state")

    def test_bare_prefix_maps_to_root(self):
        handler = _StubHandler("/autopower", "/autopower")
        handler.strip_base_path()
        self.assertEqual(handler.path, "/")

    def test_unrelated_prefix_is_not_stripped(self):
        handler = _StubHandler("/autopower", "/autopowerful/api/state")
        handler.strip_base_path()
        self.assertEqual(handler.path, "/autopowerful/api/state")


class _JsonStub:
    read_json = AutoPowerHandler.read_json

    def __init__(self, content_type, body=b"{}"):
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        self.rfile = io.BytesIO(body)


class ReadJsonTests(unittest.TestCase):
    def test_accepts_json_content_type(self):
        self.assertEqual(_JsonStub("application/json; charset=utf-8", b'{"a": 1}').read_json(), {"a": 1})

    def test_rejects_form_content_types_to_block_csrf(self):
        for content_type in ("text/plain", "application/x-www-form-urlencoded", ""):
            with self.assertRaises(ApiError) as ctx:
                _JsonStub(content_type).read_json()
            self.assertEqual(ctx.exception.status, 415)


class ExecutorStateTests(unittest.TestCase):
    def _state(self, temp_dir, status, now):
        from unittest import mock

        from src import autopower_server

        status_path = Path(temp_dir) / "status.json"
        installed = Path(temp_dir) / "autopower_executor.py"
        installed.write_text("")
        if status is not None:
            status_path.write_text(json.dumps(status))
        with mock.patch.object(autopower_server, "EXECUTOR_STATUS_PATH", status_path), \
                mock.patch.object(autopower_server, "INSTALLED_EXECUTOR", installed):
            return autopower_server.executor_state(Path("/data"), now=now)

    def test_missing_when_not_deployed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._state(temp_dir, None, None)
        self.assertEqual(result["state"], "missing")
        self.assertIn("--install /data", result["deployCommand"])

    def test_ok_when_recently_run(self):
        import datetime as dt

        from src.autopower_executor import EXECUTOR_VERSION

        now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc)
        status = {"version": EXECUTOR_VERSION, "lastRun": "2026-10-16T11:59:00+00:00", "dataDir": "/data"}
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(self._state(temp_dir, status, now)["state"], "ok")

    def test_outdated_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._state(temp_dir, {"version": "0.0.1"}, None)
        self.assertEqual(result["state"], "outdated")

    def test_error_when_cron_stopped(self):
        import datetime as dt

        from src.autopower_executor import EXECUTOR_VERSION

        now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc)
        status = {"version": EXECUTOR_VERSION, "lastRun": "2026-10-16T11:50:00+00:00", "dataDir": "/data"}
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(self._state(temp_dir, status, now)["state"], "error")

    def test_rtc_wake_converted_to_system_time(self):
        from unittest import mock

        from src import autopower_server

        with tempfile.TemporaryDirectory() as temp_dir:
            since_epoch = Path(temp_dir) / "since_epoch"
            wakealarm = Path(temp_dir) / "wakealarm"
            # RTC 走北京时间：since_epoch 与 wakealarm 都比真实时刻多 8 小时
            since_epoch.write_text(f"{1_000_000_000 + 8 * 3600}\n")
            wakealarm.write_text(f"{1_000_036_000 + 8 * 3600}\n")
            with mock.patch.object(autopower_server, "RTC_SINCE_EPOCH_PATH", since_epoch), \
                    mock.patch.object(autopower_server, "RTC_WAKEALARM_PATH", wakealarm):
                rtc = autopower_server.read_rtc(system_epoch=1_000_000_000)
                self.assertEqual(rtc, {"available": True, "offset": 8 * 3600, "wake": 1_000_036_000})
                wakealarm.write_text("")
                self.assertIsNone(autopower_server.read_rtc(system_epoch=1_000_000_000)["wake"])

    def test_deploy_command_quotes_paths(self):
        from src import autopower_server

        command = autopower_server.deploy_command(Path("/vol1/@appdata/auto power"))
        self.assertIn("--install '/vol1/@appdata/auto power'", command)


class DesktopConfigTests(unittest.TestCase):
    def test_manifest_declares_app_category(self):
        manifest_path = Path(__file__).resolve().parents[1] / "fpk" / "manifest"
        manifest_text = manifest_path.read_text()

        self.assertIn("category              = system", manifest_text)


if __name__ == "__main__":
    unittest.main()
