import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import autopower_executor as executor


TZ = dt.timezone(dt.timedelta(hours=8))


class ExecutorTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.data_dir = root / "data"
        self.data_dir.mkdir()
        anchor = root / "data-dir"
        anchor.write_text(f"{self.data_dir}\n")
        self.status_path = root / "state" / "status.json"
        self.wakes = []
        patches = [
            mock.patch.object(executor, "DATA_DIR_ANCHOR", anchor),
            mock.patch.object(executor, "STATUS_PATH", self.status_path),
            mock.patch.object(executor, "read_boot_id", return_value="boot-1"),
            mock.patch.object(executor, "write_rtc_wake", side_effect=self.record_wake),
            # 默认假设 RTC 里的闹钟与上次写入的一致
            mock.patch.object(executor, "rtc_alarm_matches", return_value=True),
            mock.patch.object(executor, "log"),
        ]
        self.mocks = {}
        for patch in patches:
            self.mocks[patch.attribute] = patch.start()
            self.addCleanup(patch.stop)

    def record_wake(self, timestamp):
        self.wakes.append(timestamp)
        return 0

    def write_schedules(self, schedules):
        (self.data_dir / "schedules.json").write_text(json.dumps({"schedules": schedules}))

    def status(self):
        return json.loads(self.status_path.read_text())


class LoadSchedulesTests(ExecutorTestCase):
    def test_missing_file_means_no_schedules(self):
        self.assertEqual(executor.load_schedules(self.data_dir), [])

    def test_skips_invalid_schedules(self):
        self.write_schedules([
            {"id": "ok", "operation": "wake", "days": "daily", "hour": 7, "minute": 0},
            {"id": "bad", "operation": "rm -rf", "days": "daily", "hour": 7, "minute": 0},
            "not-an-object",
        ])
        self.assertEqual([s["id"] for s in executor.load_schedules(self.data_dir)], ["ok"])

    def test_rejects_symlinked_schedules(self):
        target = Path(self.temp.name) / "secret"
        target.write_text("{}")
        os.symlink(target, self.data_dir / "schedules.json")
        with self.assertRaises(executor.ExecutorError):
            executor.load_schedules(self.data_dir)

    def test_rejects_oversized_and_corrupt_files(self):
        path = self.data_dir / "schedules.json"
        path.write_text(" " * (executor.SCHEDULES_MAX_BYTES + 1))
        with self.assertRaises(executor.ExecutorError):
            executor.load_schedules(self.data_dir)
        path.write_text("{broken")
        with self.assertRaises(executor.ExecutorError):
            executor.load_schedules(self.data_dir)


class DataDirTests(unittest.TestCase):
    def test_rejects_relative_and_root_paths(self):
        for raw in ("relative/path", "/"):
            with self.subTest(raw=raw), self.assertRaises(executor.ExecutorError):
                executor.validate_data_dir(raw)

    def test_missing_directory_is_reported_separately(self):
        with self.assertRaises(executor.DataDirMissing):
            executor.validate_data_dir("/nonexistent/autopower-data")


class RunOnceTests(ExecutorTestCase):
    def test_powers_off_once_when_shutdown_due(self):
        self.write_schedules([{"id": "night", "operation": "shutdown", "days": "daily", "hour": 23, "minute": 0}])
        now = dt.datetime(2026, 10, 16, 23, 0, 20, tzinfo=TZ)
        with mock.patch.object(executor.subprocess, "run") as run:
            self.assertEqual(executor.run_once(now), 0)
            executor.run_once(now + dt.timedelta(seconds=30))
        run.assert_called_once_with([executor.POWEROFF], check=False)
        status = self.status()
        self.assertEqual(status["lastShutdownSchedule"], "night")
        self.assertEqual(status["history"], [{"time": "2026-10-16T23:00:20+08:00", "schedule": "night"}])

    def test_history_is_capped(self):
        self.write_schedules([{"id": "night", "operation": "shutdown", "days": "daily", "hour": 23, "minute": 0}])
        start = dt.datetime(2026, 10, 1, 23, 0, tzinfo=TZ)
        with mock.patch.object(executor.subprocess, "run"):
            for day in range(executor.HISTORY_LIMIT + 2):
                executor.run_once(start + dt.timedelta(days=day))
        history = self.status()["history"]
        self.assertEqual(len(history), executor.HISTORY_LIMIT)
        self.assertTrue(history[0]["time"].startswith("2026-10-12"))

    def test_ignores_disabled_other_minutes_and_other_days(self):
        self.write_schedules([
            {"id": "off", "enabled": False, "operation": "shutdown", "days": "daily", "hour": 23, "minute": 0},
            {"id": "later", "operation": "shutdown", "days": "daily", "hour": 23, "minute": 1},
            # 2026-10-16 是周五，只在周末关机的计划不应触发
            {"id": "weekend", "operation": "shutdown", "days": "holiday", "hour": 23, "minute": 0},
        ])
        with mock.patch.object(executor.subprocess, "run") as run:
            executor.run_once(dt.datetime(2026, 10, 16, 23, 0, tzinfo=TZ))
        run.assert_not_called()

    def test_writes_wake_only_when_changed(self):
        self.write_schedules([{"id": "w", "operation": "wake", "days": "daily", "hour": 7, "minute": 30}])
        now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=TZ)
        executor.run_once(now)
        executor.run_once(now + dt.timedelta(minutes=1))
        expected = int(dt.datetime(2026, 10, 17, 7, 30, tzinfo=TZ).timestamp())
        self.assertEqual(self.wakes, [expected])
        self.assertEqual(self.status()["nextWake"], expected)
        self.assertIsNone(self.status()["lastError"])

    def test_rewrites_wake_when_rtc_alarm_was_changed(self):
        self.write_schedules([{"id": "w", "operation": "wake", "days": "daily", "hour": 7, "minute": 30}])
        now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=TZ)
        executor.run_once(now)
        # 其他程序清除了 RTC 闹钟
        self.mocks["rtc_alarm_matches"].return_value = False
        executor.run_once(now + dt.timedelta(minutes=1))
        self.assertEqual(len(self.wakes), 2)

    def test_rewrites_wake_after_reboot(self):
        self.write_schedules([{"id": "w", "operation": "wake", "days": "daily", "hour": 7, "minute": 30}])
        now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=TZ)
        executor.run_once(now)
        self.mocks["read_boot_id"].return_value = "boot-2"
        executor.run_once(now + dt.timedelta(minutes=1))
        self.assertEqual(len(self.wakes), 2)

    def test_clears_wake_when_data_dir_removed(self):
        self.write_schedules([{"id": "w", "operation": "wake", "days": "daily", "hour": 7, "minute": 30}])
        now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=TZ)
        executor.run_once(now)
        (self.data_dir / "schedules.json").unlink()
        self.data_dir.rmdir()
        self.assertEqual(executor.run_once(now + dt.timedelta(minutes=1)), 1)
        self.assertIsNone(self.wakes[-1])
        self.assertIsNone(self.status()["nextWake"])
        self.assertIn("数据目录不存在", self.status()["lastError"])

    def test_records_errors_in_status(self):
        (self.data_dir / "schedules.json").write_text("{broken")
        self.assertEqual(executor.run_once(dt.datetime(2026, 10, 16, 12, 0, tzinfo=TZ)), 1)
        self.assertIn("解析失败", self.status()["lastError"])


class SetWakeBeforeShutdownTests(ExecutorTestCase):
    def test_always_rewrites_wake(self):
        self.write_schedules([{"id": "w", "operation": "wake", "days": "daily", "hour": 7, "minute": 30}])
        self.assertEqual(executor.set_wake_before_shutdown(), 0)
        self.assertEqual(executor.set_wake_before_shutdown(), 0)
        self.assertEqual(len(self.wakes), 2)
        self.assertIsNotNone(self.wakes[0])

    def test_keeps_existing_alarm_when_data_dir_missing(self):
        (self.data_dir).rename(Path(self.temp.name) / "moved")
        self.assertEqual(executor.set_wake_before_shutdown(), 1)
        # 关机时存储卷可能已卸载，此时不能清掉 cron 早已写好的闹钟
        self.assertEqual(self.wakes, [])


class RtcWakeTests(unittest.TestCase):
    """write_rtc_wake / rtc_alarm_matches 按测得的 RTC 偏差换算 wakealarm 的值。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.wakealarm = root / "wakealarm"
        self.since_epoch = root / "since_epoch"
        for patch in (
            mock.patch.object(executor, "WAKEALARM_PATH", self.wakealarm),
            mock.patch.object(executor, "RTC_SINCE_EPOCH_PATH", self.since_epoch),
            mock.patch.object(executor.time, "time", return_value=1_000_000_000),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_utc_rtc_writes_timestamp_as_is(self):
        self.since_epoch.write_text("1000000003\n")
        self.assertEqual(executor.write_rtc_wake(1_000_036_000), 0)
        self.assertEqual(self.wakealarm.read_text(), "1000036000\n")
        self.assertTrue(executor.rtc_alarm_matches(1_000_036_000))

    def test_localtime_rtc_adds_timezone_offset(self):
        # RTC 走北京时间：读数比系统时钟快 8 小时（带几秒漂移）
        self.since_epoch.write_text(f"{1_000_000_000 + 8 * 3600 - 5}\n")
        self.assertEqual(executor.write_rtc_wake(1_000_036_000), 8 * 3600)
        self.assertEqual(self.wakealarm.read_text(), f"{1_000_036_000 + 8 * 3600}\n")
        self.assertTrue(executor.rtc_alarm_matches(1_000_036_000))

    def test_unreadable_rtc_assumes_utc(self):
        self.assertEqual(executor.write_rtc_wake(1_000_036_000), 0)
        self.assertEqual(self.wakealarm.read_text(), "1000036000\n")

    def test_clear_alarm(self):
        self.wakealarm.write_text("123\n")
        executor.write_rtc_wake(None)
        self.assertEqual(self.wakealarm.read_text(), "0\n")
        self.assertTrue(executor.rtc_alarm_matches(None))

    def test_detects_changed_or_cleared_alarm(self):
        self.since_epoch.write_text("1000000000\n")
        self.wakealarm.write_text("")
        self.assertIsNone(executor.read_rtc_alarm())
        self.assertFalse(executor.rtc_alarm_matches(1_000_036_000))
        self.wakealarm.write_text("1000099999\n")
        self.assertFalse(executor.rtc_alarm_matches(1_000_036_000))
        self.assertFalse(executor.rtc_alarm_matches(None))


class InstallTests(unittest.TestCase):
    """部署与卸载只写入补丁后的临时路径，验证生成的 cron / systemd 配置。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.data_dir = root / "data"
        self.data_dir.mkdir()
        self.paths = {
            "INSTALL_DIR": root / "lib",
            "INSTALLED_EXECUTOR": root / "lib" / "autopower_executor.py",
            "CONFIG_DIR": root / "etc",
            "DATA_DIR_ANCHOR": root / "etc" / "data-dir",
            "STATE_DIR": root / "state",
            "STATUS_PATH": root / "state" / "status.json",
            "CRON_FILE": root / "cron.d" / "autopower",
            "SYSTEMD_SERVICE": root / "systemd" / "autopower-rtc-wake.service",
            "LEGACY_WAKE_SCRIPT": root / "legacy.sh",
        }
        self.paths["LEGACY_WAKE_SCRIPT"].write_text("#!/bin/sh\n")
        patches = [mock.patch.object(executor, name, value) for name, value in self.paths.items()]
        patches += [
            mock.patch.object(executor.os, "geteuid", return_value=0),
            mock.patch.object(executor.shutil, "which", return_value=None),
            mock.patch.object(executor, "write_rtc_wake", return_value=0),
            mock.patch.object(executor, "rtc_alarm_matches", return_value=True),
            mock.patch.object(executor, "read_boot_id", return_value="boot-1"),
            mock.patch("builtins.print"),
            mock.patch.object(executor.sys, "stderr"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_install_writes_root_owned_copies_and_units(self):
        with mock.patch.object(executor.subprocess, "run") as run:
            self.assertEqual(executor.main(["--install", str(self.data_dir)]), 0)

        self.assertTrue(self.paths["INSTALLED_EXECUTOR"].exists())
        self.assertTrue((self.paths["INSTALL_DIR"] / "autopower_core.py").exists())
        self.assertEqual(self.paths["DATA_DIR_ANCHOR"].read_text(), f"{self.data_dir}\n")
        cron = self.paths["CRON_FILE"].read_text()
        self.assertIn(f"* * * * * root {executor.python_path()} -I {self.paths['INSTALLED_EXECUTOR']} --run", cron)
        self.assertTrue(cron.endswith("\n"))
        service = self.paths["SYSTEMD_SERVICE"].read_text()
        self.assertIn(f"ExecStop={executor.python_path()} -I {self.paths['INSTALLED_EXECUTOR']} --set-wake", service)
        self.assertFalse(self.paths["LEGACY_WAKE_SCRIPT"].exists())
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["systemctl", "daemon-reload"], commands)
        self.assertIn(["systemctl", "restart", "autopower-rtc-wake.service"], commands)
        status = json.loads(self.paths["STATUS_PATH"].read_text())
        self.assertEqual(status["version"], executor.EXECUTOR_VERSION)
        self.assertEqual(status["dataDir"], str(self.data_dir))

    def test_install_rejects_missing_data_dir(self):
        with mock.patch.object(executor.subprocess, "run") as run:
            self.assertEqual(executor.main(["--install", str(self.data_dir / "missing")]), 1)
        run.assert_not_called()
        self.assertFalse(self.paths["CRON_FILE"].exists())

    def test_uninstall_removes_everything(self):
        with mock.patch.object(executor.subprocess, "run"):
            executor.main(["--install", str(self.data_dir)])
            self.assertEqual(executor.main(["--uninstall"]), 0)
        for name in ("INSTALL_DIR", "CONFIG_DIR", "STATE_DIR", "CRON_FILE", "SYSTEMD_SERVICE"):
            self.assertFalse(self.paths[name].exists(), name)
        executor.write_rtc_wake.assert_called_with(None)


class CommandLineTests(unittest.TestCase):
    def test_privileged_commands_require_root(self):
        with mock.patch.object(executor.os, "geteuid", return_value=1000), mock.patch.object(executor.sys, "stderr"):
            for argv in (["--run"], ["--set-wake"], ["--install", "/tmp"], ["--uninstall"]):
                with self.subTest(argv=argv):
                    self.assertEqual(executor.main(argv), 1)

    def test_unknown_arguments_show_usage(self):
        with mock.patch.object(executor.sys, "stderr"):
            self.assertEqual(executor.main(["--run", "/etc"]), 2)
            self.assertEqual(executor.main([]), 2)

    def test_python_path_is_absolute(self):
        self.assertTrue(os.path.isabs(executor.python_path()))
        with mock.patch.object(executor.sys, "executable", ""):
            self.assertEqual(executor.python_path(), executor.DEFAULT_PYTHON)


if __name__ == "__main__":
    unittest.main()
