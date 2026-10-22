import datetime as dt
import unittest

from src.autopower_core import (
    ScheduleValidationError,
    next_event,
    next_occurrence,
    next_wake_timestamp,
    rtc_alarm_value,
    rtc_offset,
    strip_managed_crontab,
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

    def test_strip_managed_crontab_keeps_unmanaged_lines(self):
        existing = "5 1 * * * /usr/bin/true\n# BEGIN AUTOPOWER\n0 20 * * * /sbin/poweroff # autopower:a\n# END AUTOPOWER\n"

        result = strip_managed_crontab(existing)

        self.assertEqual(result, "5 1 * * * /usr/bin/true")

    def test_invalid_schedule_rejects_bad_time(self):
        with self.assertRaises(ScheduleValidationError):
            validate_schedule({"operation": "wake", "days": "daily", "hour": 24, "minute": 0})


class NextEventTests(unittest.TestCase):
    def test_picks_soonest_enabled_event_regardless_of_order(self):
        now = dt.datetime(2026, 6, 18, 12, 0, tzinfo=dt.timezone.utc)
        schedules = [
            {"id": "late-wake", "enabled": True, "operation": "wake", "days": "daily", "hour": 20, "minute": 0},
            {"id": "disabled", "enabled": False, "operation": "wake", "days": "daily", "hour": 12, "minute": 30},
            {"id": "soon-off", "enabled": True, "operation": "shutdown", "days": "daily", "hour": 13, "minute": 0},
        ]

        event = next_event(schedules, now)

        self.assertEqual(event["id"], "soon-off")
        self.assertEqual(event["operation"], "shutdown")
        self.assertEqual(event["timestamp"], int(dt.datetime(2026, 6, 18, 13, 0, tzinfo=dt.timezone.utc).timestamp()))

    def test_returns_none_without_enabled_schedules(self):
        self.assertIsNone(next_event([{"enabled": False, "operation": "wake", "hour": 1, "minute": 0}]))


if __name__ == "__main__":
    unittest.main()


class RtcOffsetTests(unittest.TestCase):
    def test_utc_rtc_has_no_offset(self):
        self.assertEqual(rtc_offset(1_000_000_004, 1_000_000_000), 0)

    def test_localtime_rtc_offset_rounds_to_timezone(self):
        self.assertEqual(rtc_offset(1_000_000_000 + 8 * 3600 + 40, 1_000_000_000), 8 * 3600)
        self.assertEqual(rtc_offset(1_000_000_000 - 5 * 3600 - 1800, 1_000_000_000), -5 * 3600 - 1800)

    def test_alarm_value_adds_offset(self):
        self.assertEqual(rtc_alarm_value(1_000_036_000, 8 * 3600), 1_000_064_800)
