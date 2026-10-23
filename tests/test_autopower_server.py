import datetime as dt
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from src import autopower_server
from src.autopower_executor import EXECUTOR_VERSION
from src.autopower_server import (
    ApiError,
    AppState,
    AutoPowerHandler,
    create_schedule,
    delete_schedule,
    set_all_enabled,
    update_schedule,
)


ROOT = Path(__file__).resolve().parents[1]


def wake(**overrides):
    schedule = {"enabled": True, "operation": "wake", "days": "daily", "hour": 9, "minute": 0}
    schedule.update(overrides)
    return schedule


class StateTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)
        self.state = AppState(self.data_dir)
        patch = mock.patch.object(autopower_server, "log")
        patch.start()
        self.addCleanup(patch.stop)

    def saved(self):
        return json.loads((self.data_dir / "schedules.json").read_text())["schedules"]


class AppStateTests(StateTestCase):
    def test_missing_file_means_no_schedules(self):
        # 执行器读到的也是“没有计划”，界面不能展示一条实际不会执行的默认计划
        self.assertEqual(self.state.load(), {"schedules": []})

    def test_corrupt_file_is_backed_up(self):
        (self.data_dir / "schedules.json").write_text("{broken")
        self.assertEqual(self.state.load(), {"schedules": []})
        self.assertFalse((self.data_dir / "schedules.json").exists())
        self.assertEqual(len(list(self.data_dir.glob("schedules.corrupt-*.json"))), 1)

    def test_invalid_entries_are_skipped(self):
        (self.data_dir / "schedules.json").write_text(json.dumps({"schedules": [wake(id="ok"), wake(id="bad", hour=99)]}))
        self.assertEqual([item["id"] for item in self.state.load()["schedules"]], ["ok"])

    def test_save_writes_atomically_without_temp_leftovers(self):
        self.state.save({"schedules": [wake(id="a")]})
        self.assertEqual([item["id"] for item in self.saved()], ["a"])
        self.assertEqual(sorted(path.name for path in self.data_dir.iterdir()), ["schedules.json"])


class ScheduleCrudTests(StateTestCase):
    def test_create_persists_and_generates_server_id(self):
        existing = create_schedule(self.state, wake())
        created = create_schedule(self.state, wake(id=existing["id"], operation="shutdown", days="custom", weekdays=[4]))

        self.assertNotEqual(created["id"], existing["id"])
        self.assertEqual([item["operation"] for item in self.saved()], ["wake", "shutdown"])

    def test_display_fields_are_not_persisted(self):
        create_schedule(self.state, wake(trigger="每天 09:00"))
        self.assertNotIn("trigger", self.saved()[0])

    def test_update_replaces_existing_plan(self):
        existing = create_schedule(self.state, wake())
        updated = update_schedule(self.state, existing["id"], wake(enabled=False, hour=10, minute=15, note="周末"))

        self.assertEqual(updated["id"], existing["id"])
        self.assertEqual((updated["enabled"], updated["hour"], updated["minute"], updated["note"]), (False, 10, 15, "周末"))
        self.assertEqual(self.saved()[0]["hour"], 10)

    def test_update_and_delete_unknown_id_return_404(self):
        for action in (lambda: update_schedule(self.state, "nope", wake()), lambda: delete_schedule(self.state, "nope")):
            with self.assertRaises(ApiError) as ctx:
                action()
            self.assertEqual(ctx.exception.status, 404)

    def test_delete_removes_only_target(self):
        first = create_schedule(self.state, wake())
        second = create_schedule(self.state, wake(hour=10))
        delete_schedule(self.state, first["id"])
        self.assertEqual([item["id"] for item in self.saved()], [second["id"]])

    def test_set_all_enabled(self):
        create_schedule(self.state, wake())
        create_schedule(self.state, wake(enabled=False, hour=10))
        self.assertEqual(set_all_enabled(self.state, True), {"ok": True, "count": 2})
        self.assertTrue(all(item["enabled"] for item in self.saved()))
        with self.assertRaises(ApiError):
            set_all_enabled(self.state, "yes")


class _StubHandler:
    """不打开 socket，单独验证路径前缀处理。"""

    strip_base_path = AutoPowerHandler.strip_base_path

    def __init__(self, base_path, path):
        self.base_path = base_path
        self.path = path


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

    def __init__(self, content_type, body=b"{}", length=None):
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body) if length is None else length)}
        self.rfile = io.BytesIO(body)


class ReadJsonTests(unittest.TestCase):
    def assert_status(self, stub, status):
        with self.assertRaises(ApiError) as ctx:
            stub.read_json()
        self.assertEqual(ctx.exception.status, status)

    def test_accepts_json_content_type(self):
        self.assertEqual(_JsonStub("application/json; charset=utf-8", b'{"a": 1}').read_json(), {"a": 1})

    def test_rejects_form_content_types_to_block_csrf(self):
        for content_type in ("text/plain", "application/x-www-form-urlencoded", ""):
            with self.subTest(content_type=content_type):
                self.assert_status(_JsonStub(content_type), 415)

    def test_rejects_bad_lengths_and_bodies(self):
        self.assert_status(_JsonStub("application/json", length=-1), 400)
        self.assert_status(_JsonStub("application/json", length="abc"), 400)
        self.assert_status(_JsonStub("application/json", length=autopower_server.MAX_BODY_BYTES + 1), 413)
        self.assert_status(_JsonStub("application/json", b"[1, 2]"), 400)
        self.assert_status(_JsonStub("application/json", b"{oops"), 400)
        self.assert_status(_JsonStub("application/json", b"\xff\xfe"), 400)


class ExecutorStateTests(unittest.TestCase):
    def _state(self, temp_dir, status, now, installed=True):
        status_path = Path(temp_dir) / "status.json"
        executor_path = Path(temp_dir) / "autopower_executor.py"
        if installed:
            executor_path.write_text("")
        if status is not None:
            status_path.write_text(json.dumps(status))
        with mock.patch.object(autopower_server, "EXECUTOR_STATUS_PATH", status_path), \
                mock.patch.object(autopower_server, "INSTALLED_EXECUTOR", executor_path):
            return autopower_server.executor_state(Path("/data"), now=now)

    def ok_status(self, **overrides):
        status = {"version": EXECUTOR_VERSION, "lastRun": "2026-10-16T11:59:00+00:00", "dataDir": "/data"}
        status.update(overrides)
        return status

    now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc)

    def test_missing_when_not_deployed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._state(temp_dir, None, None)
        self.assertEqual(result["state"], "missing")
        self.assertIn("--install /data", result["deployCommand"])

    def test_missing_when_executor_file_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(self._state(temp_dir, self.ok_status(), self.now, installed=False)["state"], "missing")

    def test_ok_when_recently_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._state(temp_dir, self.ok_status(history=[{"time": "2026-10-15T23:00:00+00:00", "schedule": "a"}]), self.now)
        self.assertEqual(result["state"], "ok")
        self.assertEqual(result["history"][0]["schedule"], "a")

    def test_outdated_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(self._state(temp_dir, {"version": "0.0.1"}, None)["state"], "outdated")

    def test_error_when_cron_stopped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._state(temp_dir, self.ok_status(lastRun="2026-10-16T11:50:00+00:00"), self.now)
        self.assertEqual(result["state"], "error")
        self.assertIn("cron", result["lastError"])

    def test_error_when_executor_reports_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._state(temp_dir, self.ok_status(lastError="boom"), self.now)
        self.assertEqual((result["state"], result["lastError"]), ("error", "boom"))

    def test_error_when_data_dir_differs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self._state(temp_dir, self.ok_status(dataDir="/other"), self.now)
        self.assertEqual(result["state"], "error")
        self.assertIn("/other", result["lastError"])

    def test_rtc_wake_converted_to_system_time(self):
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
        command = autopower_server.deploy_command(Path("/vol1/@appdata/auto power"))
        self.assertIn("--install '/vol1/@appdata/auto power'", command)


class HttpApiTests(unittest.TestCase):
    """启动真实的 HTTP 服务，走完整的请求路由。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        patches = [
            mock.patch.object(autopower_server, "log"),
            mock.patch.object(autopower_server, "EXECUTOR_STATUS_PATH", root / "status.json"),
            mock.patch.object(autopower_server, "INSTALLED_EXECUTOR", root / "missing.py"),
            mock.patch.object(AutoPowerHandler, "state", AppState(root / "data")),
            mock.patch.object(AutoPowerHandler, "web_dir", ROOT / "web"),
            mock.patch.object(AutoPowerHandler, "base_path", ""),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), AutoPowerHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(connection.close)
        headers = {"Content-Type": content_type} if body is not None else {}
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        if response.getheader("Content-Type", "").startswith("application/json"):
            return response.status, json.loads(raw)
        return response.status, raw

    def test_full_schedule_lifecycle(self):
        status, state = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["schedules"], [])
        self.assertEqual(state["executor"]["state"], "missing")
        self.assertIsNone(state["nextEvent"])

        status, created = self.request("POST", "/api/schedules", wake(note="上班"))
        self.assertEqual(status, 201)
        status, _ = self.request("POST", "/api/schedules", wake(operation="shutdown"))
        self.assertEqual(status, 201)

        status, state = self.request("GET", "/api/state")
        self.assertEqual(len(state["schedules"]), 2)
        self.assertEqual(state["schedules"][0]["trigger"], "每天 09:00")
        self.assertEqual(state["conflicts"][0]["kind"], "opposite")
        self.assertTrue(state["upcoming"])
        self.assertIn("localTime", state["nextEvent"])

        status, updated = self.request("PUT", f"/api/schedules/{created['id']}", wake(hour=8))
        self.assertEqual((status, updated["hour"]), (200, 8))

        status, result = self.request("PUT", "/api/schedules", {"enabled": False})
        self.assertEqual((status, result["count"]), (200, 2))
        status, state = self.request("GET", "/api/state")
        self.assertFalse(any(item["enabled"] for item in state["schedules"]))
        self.assertEqual(state["upcoming"], [])

        status, _ = self.request("DELETE", f"/api/schedules/{created['id']}")
        self.assertEqual(status, 200)
        status, _ = self.request("DELETE", f"/api/schedules/{created['id']}")
        self.assertEqual(status, 404)

    def test_reboot_schedule_round_trip(self):
        status, created = self.request("POST", "/api/schedules", wake(operation="reboot", note="每周重启"))
        self.assertEqual((status, created["operation"]), (201, "reboot"))
        status, _ = self.request("POST", "/api/schedules", wake(operation="shutdown"))
        status, state = self.request("GET", "/api/state")
        self.assertEqual(state["nextEvent"]["operation"], "shutdown")
        self.assertEqual({event["operation"] for event in state["upcoming"]}, {"shutdown", "reboot"})
        self.assertEqual(state["conflicts"][0]["operations"], ["shutdown", "reboot"])

    def test_validation_and_routing_errors(self):
        status, body = self.request("POST", "/api/schedules", wake(hour=30))
        self.assertEqual(status, 400)
        self.assertIn("hour", body["error"])
        status, _ = self.request("POST", "/api/schedules", b"hour=1", content_type="application/x-www-form-urlencoded")
        self.assertEqual(status, 415)
        status, _ = self.request("GET", "/api/unknown")
        self.assertEqual(status, 404)

    def test_serves_static_index(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"app.js", body)


class PackageConfigTests(unittest.TestCase):
    def test_manifest_declares_category_and_supported_platform(self):
        manifest = {}
        for line in (ROOT / "fpk" / "manifest").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                manifest[key.strip()] = value.strip()
        self.assertEqual(manifest["category"], "system")
        self.assertIn(manifest["platform"], ("x86", "arm", "all"))

    def test_package_runs_unprivileged(self):
        privilege = json.loads((ROOT / "fpk" / "config" / "privilege").read_text(encoding="utf-8"))
        self.assertEqual(privilege["defaults"]["run-as"], "package")


if __name__ == "__main__":
    unittest.main()
