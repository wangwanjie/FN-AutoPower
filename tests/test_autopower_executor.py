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
            mock.patch.object(executor, "write_rtc_wake", side_effect=self.wakes.append),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)

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
        ])
        self.assertEqual([s["id"] for s in executor.load_schedules(self.data_dir)], ["ok"])

    def test_rejects_symlinked_schedules(self):
        target = Path(self.temp.name) / "secret"
        target.write_text("{}")
        os.symlink(target, self.data_dir / "schedules.json")
        with self.assertRaises(executor.ExecutorError):
            executor.load_schedules(self.data_dir)


class RunOnceTests(ExecutorTestCase):
    def test_powers_off_once_when_shutdown_due(self):
        self.write_schedules([{"id": "night", "operation": "shutdown", "days": "daily", "hour": 23, "minute": 0}])
        now = dt.datetime(2026, 10, 16, 23, 0, 20, tzinfo=TZ)
        with mock.patch.object(executor.subprocess, "run") as run:
            executor.run_once(now)
            executor.run_once(now + dt.timedelta(seconds=30))
        run.assert_called_once_with([executor.POWEROFF], check=False)
        self.assertEqual(self.status()["lastShutdownSchedule"], "night")

    def test_ignores_disabled_and_other_minutes(self):
        self.write_schedules([
            {"id": "off", "enabled": False, "operation": "shutdown", "days": "daily", "hour": 23, "minute": 0},
            {"id": "later", "operation": "shutdown", "days": "daily", "hour": 23, "minute": 1},
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

    def test_clears_wake_when_data_dir_removed(self):
        self.write_schedules([{"id": "w", "operation": "wake", "days": "daily", "hour": 7, "minute": 30}])
        now = dt.datetime(2026, 10, 16, 12, 0, tzinfo=TZ)
        executor.run_once(now)
        (self.data_dir / "schedules.json").unlink()
        self.data_dir.rmdir()
        executor.run_once(now + dt.timedelta(minutes=1))
        self.assertIsNone(self.wakes[-1])
        self.assertIn("数据目录不存在", self.status()["lastError"])


class RtcWakeTests(unittest.TestCase):
    """write_rtc_wake 按测得的 RTC 偏差补偿写入 wakealarm 的值。"""

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

    def test_localtime_rtc_adds_timezone_offset(self):
        # RTC 走北京时间：读数比系统时钟快 8 小时（带几秒漂移）
        self.since_epoch.write_text(f"{1_000_000_000 + 8 * 3600 - 5}\n")
        self.assertEqual(executor.write_rtc_wake(1_000_036_000), 8 * 3600)
        self.assertEqual(self.wakealarm.read_text(), f"{1_000_036_000 + 8 * 3600}\n")

    def test_unreadable_rtc_assumes_utc(self):
        self.assertEqual(executor.write_rtc_wake(1_000_036_000), 0)
        self.assertEqual(self.wakealarm.read_text(), "1000036000\n")

    def test_clear_alarm(self):
        self.wakealarm.write_text("123\n")
        executor.write_rtc_wake(None)
        self.assertEqual(self.wakealarm.read_text(), "0\n")


class CommandLineTests(unittest.TestCase):
    def test_privileged_commands_require_root(self):
        with mock.patch.object(executor.os, "geteuid", return_value=1000):
            self.assertEqual(executor.main(["--run"]), 1)
            self.assertEqual(executor.main(["--install", "/tmp"]), 1)

    def test_unknown_arguments_show_usage(self):
        self.assertEqual(executor.main(["--run", "/etc"]), 2)


if __name__ == "__main__":
    unittest.main()
