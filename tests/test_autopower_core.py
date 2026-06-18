import datetime as dt
import unittest

from src.autopower_core import (
    ScheduleValidationError,
    next_occurrence,
    next_wake_timestamp,
    render_managed_crontab,
    validate_schedule,
)


class AutoPowerCoreTests(unittest.TestCase):
    def test_daily_wake_uses_today_when_time_has_not_passed(self):
        schedule = validate_schedule(
            {
                "id": "wake1",
                "enabled": True,
                "operation": "wake",
                "days": "daily",
                "hour": 15,
                "minute": 0,
            }
        )
        now = dt.datetime(2026, 6, 18, 14, 30, tzinfo=dt.timezone.utc)

        result = next_occurrence(schedule, now)

        self.assertEqual(result, dt.datetime(2026, 6, 18, 15, 0, tzinfo=dt.timezone.utc))

    def test_daily_wake_uses_tomorrow_when_time_has_passed(self):
        schedule = validate_schedule(
            {
                "id": "wake1",
                "enabled": True,
                "operation": "wake",
                "days": "daily",
                "hour": 15,
                "minute": 0,
            }
        )
        now = dt.datetime(2026, 6, 18, 23, 28, tzinfo=dt.timezone.utc)

        result = next_occurrence(schedule, now)

        self.assertEqual(result, dt.datetime(2026, 6, 19, 15, 0, tzinfo=dt.timezone.utc))

    def test_custom_weekday_wake_picks_next_matching_day(self):
        schedule = validate_schedule(
            {
                "id": "wake-friday",
                "enabled": True,
                "operation": "wake",
                "days": "custom",
                "weekdays": [4],
                "hour": 14,
                "minute": 30,
            }
        )
        now = dt.datetime(2026, 6, 18, 23, 28, tzinfo=dt.timezone.utc)

        result = next_occurrence(schedule, now)

        self.assertEqual(result, dt.datetime(2026, 6, 19, 14, 30, tzinfo=dt.timezone.utc))

    def test_next_wake_timestamp_ignores_shutdown_and_disabled_plans(self):
        schedules = [
            {"id": "off", "enabled": True, "operation": "shutdown", "days": "daily", "hour": 8, "minute": 0},
            {"id": "disabled", "enabled": False, "operation": "wake", "days": "daily", "hour": 7, "minute": 0},
            {"id": "wake", "enabled": True, "operation": "wake", "days": "daily", "hour": 15, "minute": 0},
        ]
        now = dt.datetime(2026, 6, 18, 23, 28, tzinfo=dt.timezone.utc)

        result = next_wake_timestamp(schedules, now)

        self.assertEqual(result, int(dt.datetime(2026, 6, 19, 15, 0, tzinfo=dt.timezone.utc).timestamp()))

    def test_render_managed_crontab_preserves_unmanaged_lines(self):
        schedules = [
            {"id": "a", "enabled": True, "operation": "shutdown", "days": "daily", "hour": 20, "minute": 0},
            {"id": "b", "enabled": True, "operation": "shutdown", "days": "custom", "weekdays": [4], "hour": 14, "minute": 30},
            {"id": "c", "enabled": False, "operation": "shutdown", "days": "daily", "hour": 9, "minute": 0},
            {"id": "d", "enabled": True, "operation": "wake", "days": "daily", "hour": 15, "minute": 0},
        ]
        existing = "5 1 * * * /usr/bin/true\n# BEGIN AUTOPOWER\nold\n# END AUTOPOWER\n"

        result = render_managed_crontab(existing, schedules)

        self.assertIn("5 1 * * * /usr/bin/true", result)
        self.assertIn("# BEGIN AUTOPOWER", result)
        self.assertIn("0 20 * * * /sbin/poweroff # autopower:a", result)
        self.assertIn("30 14 * * 5 /sbin/poweroff # autopower:b", result)
        self.assertNotIn("old", result)
        self.assertNotIn("autopower:c", result)
        self.assertNotIn("autopower:d", result)

    def test_invalid_schedule_rejects_bad_time(self):
        with self.assertRaises(ScheduleValidationError):
            validate_schedule({"operation": "wake", "days": "daily", "hour": 24, "minute": 0})


if __name__ == "__main__":
    unittest.main()
