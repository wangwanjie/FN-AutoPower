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


class SystemWriteGuardTests(unittest.TestCase):
    def test_sync_is_noop_when_system_writes_disabled(self):
        from unittest import mock

        from src import autopower_server

        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(autopower_server, "SYSTEM_WRITES_ENABLED", False), \
                mock.patch.object(autopower_server.subprocess, "run") as run:
            state = AppState(Path(temp_dir))
            create_schedule(state, {"operation": "shutdown", "days": "daily", "hour": 1, "minute": 0})

            warnings = autopower_server.sync_system_state(state)

            run.assert_not_called()
            self.assertEqual(len(warnings), 2)


class DesktopConfigTests(unittest.TestCase):
    def test_manifest_declares_app_category(self):
        manifest_path = Path(__file__).resolve().parents[1] / "fpk" / "manifest"
        manifest_text = manifest_path.read_text()

        self.assertIn("category              = system", manifest_text)


if __name__ == "__main__":
    unittest.main()
