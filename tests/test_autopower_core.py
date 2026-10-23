import datetime as dt
import os
import time
import unittest

from src.autopower_core import (
    NOTE_MAX_LENGTH,
    ScheduleValidationError,
    find_conflicts,
    format_trigger,
    next_event,
    next_occurrence,
    next_wake_timestamp,
    rtc_alarm_value,
    rtc_offset,
    strip_managed_crontab,
    upcoming_events,
    validate_schedule,
)


UTC = dt.timezone.utc


def plan(**overrides):
    schedule = {"id": "p", "enabled": True, "operation": "wake", "days": "daily", "hour": 15, "minute": 0}
    schedule.update(overrides)
    return schedule


class ValidateScheduleTests(unittest.TestCase):
    def test_normalizes_and_keeps_only_known_fields(self):
        result = validate_schedule(plan(trigger="每天 15:00", extra=1, hour="7", minute=5.0))

        self.assertEqual(
            result,
            {
                "id": "p",
                "enabled": True,
                "operation": "wake",
                "days": "daily",
                "weekdays": [0, 1, 2, 3, 4, 5, 6],
                "hour": 7,
                "minute": 5,
                "note": "",
            },
        )

    def test_presets_override_submitted_weekdays(self):
        self.assertEqual(validate_schedule(plan(days="weekday", weekdays=[6]))["weekdays"], [0, 1, 2, 3, 4])
        self.assertEqual(validate_schedule(plan(days="holiday"))["weekdays"], [5, 6])

    def test_custom_weekdays_are_sorted_and_deduplicated(self):
        self.assertEqual(validate_schedule(plan(days="custom", weekdays=[4, "1", 4]))["weekdays"], [1, 4])

    def test_accepts_all_operations(self):
        for operation in ("wake", "shutdown", "reboot"):
            with self.subTest(operation=operation):
                self.assertEqual(validate_schedule(plan(operation=operation))["operation"], operation)

    def test_rejects_invalid_values(self):
        invalid = [
            plan(operation="restart"),
            plan(operation=None),
            plan(hour=24),
            plan(minute=-1),
            plan(hour=True),
            plan(hour=7.5),
            plan(hour=None),
            plan(enabled="false"),
            plan(days="sometimes"),
            plan(days="custom", weekdays=[]),
            plan(days="custom", weekdays=[7]),
            plan(days="custom", weekdays="0,1"),
            plan(note=123),
            plan(note="x" * (NOTE_MAX_LENGTH + 1)),
        ]
        for schedule in invalid:
            with self.subTest(schedule=schedule), self.assertRaises(ScheduleValidationError):
                validate_schedule(schedule)

    def test_rejects_non_object(self):
        with self.assertRaises(ScheduleValidationError):
            validate_schedule(["wake"])

    def test_note_whitespace_is_collapsed(self):
        self.assertEqual(validate_schedule(plan(note="  下班\n 关机 "))["note"], "下班 关机")

    def test_generates_id_when_missing(self):
        schedule = plan()
        del schedule["id"]
        self.assertTrue(validate_schedule(schedule)["id"])


class NextOccurrenceTests(unittest.TestCase):
    def test_daily_uses_today_when_time_has_not_passed(self):
        now = dt.datetime(2026, 6, 18, 14, 30, tzinfo=UTC)
        self.assertEqual(next_occurrence(plan(), now), dt.datetime(2026, 6, 18, 15, 0, tzinfo=UTC))

    def test_daily_uses_tomorrow_when_time_has_passed(self):
        now = dt.datetime(2026, 6, 18, 23, 28, tzinfo=UTC)
        self.assertEqual(next_occurrence(plan(), now), dt.datetime(2026, 6, 19, 15, 0, tzinfo=UTC))

    def test_exact_current_minute_moves_to_next_occurrence(self):
        now = dt.datetime(2026, 6, 18, 15, 0, tzinfo=UTC)
        self.assertEqual(next_occurrence(plan(), now), dt.datetime(2026, 6, 19, 15, 0, tzinfo=UTC))

    def test_custom_weekday_picks_next_matching_day(self):
        # 2026-06-18 是周四，下一个周五是 06-19
        now = dt.datetime(2026, 6, 18, 23, 28, tzinfo=UTC)
        result = next_occurrence(plan(days="custom", weekdays=[4], hour=14, minute=30), now)
        self.assertEqual(result, dt.datetime(2026, 6, 19, 14, 30, tzinfo=UTC))

    def test_same_weekday_after_time_passed_waits_a_week(self):
        now = dt.datetime(2026, 6, 18, 16, 0, tzinfo=UTC)
        result = next_occurrence(plan(days="custom", weekdays=[3]), now)
        self.assertEqual(result, dt.datetime(2026, 6, 25, 15, 0, tzinfo=UTC))

    def test_holiday_on_weekday_jumps_to_saturday(self):
        now = dt.datetime(2026, 6, 18, 8, 0, tzinfo=UTC)
        self.assertEqual(next_occurrence(plan(days="holiday"), now), dt.datetime(2026, 6, 20, 15, 0, tzinfo=UTC))


@unittest.skipUnless(hasattr(time, "tzset"), "需要 time.tzset 切换系统时区")
class LocalTimezoneTests(unittest.TestCase):
    """不传 now 或传入不带时区的 now 时按系统时区计算，每个候选时刻单独换算偏移。"""

    def setUp(self):
        self.original_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()

    def tearDown(self):
        if self.original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.original_tz
        time.tzset()

    def test_wake_after_dst_ends_uses_new_offset(self):
        # 2026-11-01 02:00 纽约结束夏令时，10-31 中午到 11-01 07:00 跨过了切换
        now = dt.datetime(2026, 10, 31, 12, 0)
        result = next_occurrence(plan(hour=7, minute=0), now)
        expected = dt.datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
        self.assertEqual(int(result.timestamp()), int(expected.timestamp()))
        self.assertEqual((result.hour, result.minute), (7, 0))


class NextWakeAndEventTests(unittest.TestCase):
    def test_next_wake_ignores_shutdown_and_disabled_plans(self):
        schedules = [
            plan(id="off", operation="shutdown", hour=8),
            plan(id="disabled", enabled=False, hour=7),
            plan(id="wake", hour=15),
        ]
        now = dt.datetime(2026, 6, 18, 23, 28, tzinfo=UTC)
        expected = int(dt.datetime(2026, 6, 19, 15, 0, tzinfo=UTC).timestamp())
        self.assertEqual(next_wake_timestamp(schedules, now), expected)

    def test_next_wake_is_none_without_wake_plans(self):
        self.assertIsNone(next_wake_timestamp([plan(operation="shutdown")], dt.datetime(2026, 6, 18, tzinfo=UTC)))

    def test_next_event_picks_soonest_enabled_regardless_of_order(self):
        now = dt.datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
        schedules = [
            plan(id="late-wake", hour=20),
            plan(id="disabled", enabled=False, hour=12, minute=30),
            plan(id="soon-off", operation="shutdown", hour=13),
        ]
        event = next_event(schedules, now)
        self.assertEqual(event["id"], "soon-off")
        self.assertEqual(event["operation"], "shutdown")
        self.assertEqual(event["timestamp"], int(dt.datetime(2026, 6, 18, 13, 0, tzinfo=UTC).timestamp()))

    def test_next_event_none_without_enabled_schedules(self):
        self.assertIsNone(next_event([plan(enabled=False)]))


class UpcomingEventsTests(unittest.TestCase):
    def test_lists_sorted_events_within_window(self):
        now = dt.datetime(2026, 6, 18, 12, 0, tzinfo=UTC)  # 周四
        schedules = [
            plan(id="off", operation="shutdown", days="weekday", hour=23, minute=0),
            plan(id="on", days="holiday", hour=9, minute=0),
            plan(id="disabled", enabled=False),
        ]
        events = upcoming_events(schedules, now, days=3)
        stamps = [(event["id"], dt.datetime.fromtimestamp(event["timestamp"], UTC)) for event in events]
        self.assertEqual(
            stamps,
            [
                ("off", dt.datetime(2026, 6, 18, 23, 0, tzinfo=UTC)),
                ("off", dt.datetime(2026, 6, 19, 23, 0, tzinfo=UTC)),
                ("on", dt.datetime(2026, 6, 20, 9, 0, tzinfo=UTC)),
                ("on", dt.datetime(2026, 6, 21, 9, 0, tzinfo=UTC)),
            ],
        )

    def test_limit_and_same_minute_order(self):
        now = dt.datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
        schedules = [plan(id="b-off", operation="shutdown"), plan(id="a-on")]
        events = upcoming_events(schedules, now, days=7, limit=3)
        self.assertEqual([event["id"] for event in events], ["a-on", "b-off", "a-on"])

    def test_same_minute_order_includes_reboot(self):
        now = dt.datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
        schedules = [plan(id="a-re", operation="reboot"), plan(id="b-off", operation="shutdown"), plan(id="c-on")]
        events = upcoming_events(schedules, now, days=1, limit=3)
        self.assertEqual([event["operation"] for event in events], ["wake", "shutdown", "reboot"])


class ConflictTests(unittest.TestCase):
    def test_detects_wake_and_shutdown_in_same_minute(self):
        schedules = [plan(id="on", days="weekday"), plan(id="off", operation="shutdown", days="custom", weekdays=[0])]
        self.assertEqual(find_conflicts(schedules), [{"kind": "opposite", "hour": 15, "minute": 0, "ids": ["off", "on"], "operations": ["wake", "shutdown"]}])

    def test_detects_shutdown_and_reboot_in_same_minute(self):
        schedules = [plan(id="off", operation="shutdown"), plan(id="re", operation="reboot")]
        self.assertEqual(
            find_conflicts(schedules),
            [{"kind": "opposite", "hour": 15, "minute": 0, "ids": ["off", "re"], "operations": ["shutdown", "reboot"]}],
        )

    def test_detects_duplicates_once(self):
        schedules = [plan(id="a"), plan(id="b")]
        self.assertEqual(find_conflicts(schedules), [{"kind": "duplicate", "hour": 15, "minute": 0, "ids": ["a", "b"], "operations": ["wake"]}])

    def test_ignores_disabled_and_non_overlapping_days(self):
        schedules = [
            plan(id="a", days="weekday"),
            plan(id="b", operation="shutdown", days="holiday"),
            plan(id="c", enabled=False),
        ]
        self.assertEqual(find_conflicts(schedules), [])


class FormatTriggerTests(unittest.TestCase):
    def test_presets_and_custom_days(self):
        self.assertEqual(format_trigger(plan(hour=7, minute=5)), "每天 07:05")
        self.assertEqual(format_trigger(plan(days="weekday")), "平日 15:00")
        self.assertEqual(format_trigger(plan(days="custom", weekdays=[6, 0])), "周一、周日 15:00")


class CrontabTests(unittest.TestCase):
    def test_strip_managed_crontab_keeps_unmanaged_lines(self):
        existing = "5 1 * * * /usr/bin/true\n# BEGIN AUTOPOWER\n0 20 * * * /sbin/poweroff # autopower:a\n# END AUTOPOWER\n"
        self.assertEqual(strip_managed_crontab(existing), "5 1 * * * /usr/bin/true")


class RtcOffsetTests(unittest.TestCase):
    def test_utc_rtc_has_no_offset(self):
        self.assertEqual(rtc_offset(1_000_000_004, 1_000_000_000), 0)

    def test_localtime_rtc_offset_rounds_to_timezone(self):
        self.assertEqual(rtc_offset(1_000_000_000 + 8 * 3600 + 40, 1_000_000_000), 8 * 3600)
        self.assertEqual(rtc_offset(1_000_000_000 - 5 * 3600 - 1800, 1_000_000_000), -5 * 3600 - 1800)

    def test_alarm_value_adds_offset(self):
        self.assertEqual(rtc_alarm_value(1_000_036_000, 8 * 3600), 1_000_064_800)


if __name__ == "__main__":
    unittest.main()
