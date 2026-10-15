import datetime as dt
import time
from typing import Dict, Iterable, List, Optional


BEGIN_MARKER = "# BEGIN AUTOPOWER"
END_MARKER = "# END AUTOPOWER"
POWER_COMMAND = "/sbin/poweroff"

DAY_PRESETS = {
    "daily": [0, 1, 2, 3, 4, 5, 6],
    "weekday": [0, 1, 2, 3, 4],
    "holiday": [5, 6],
}


class ScheduleValidationError(ValueError):
    pass


def _coerce_int(value, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleValidationError(f"{field} must be an integer") from exc


def weekdays_for(schedule: Dict) -> List[int]:
    days = schedule.get("days", "daily")
    if days in DAY_PRESETS:
        return DAY_PRESETS[days][:]
    if days != "custom":
        raise ScheduleValidationError("days must be daily, weekday, holiday, or custom")

    raw_weekdays = schedule.get("weekdays", [])
    if not isinstance(raw_weekdays, list) or not raw_weekdays:
        raise ScheduleValidationError("custom schedules require weekdays")

    weekdays = sorted({_coerce_int(day, "weekday") for day in raw_weekdays})
    if any(day < 0 or day > 6 for day in weekdays):
        raise ScheduleValidationError("weekday must be between 0 and 6")
    return weekdays


def validate_schedule(schedule: Dict) -> Dict:
    result = dict(schedule)
    operation = result.get("operation")
    if operation not in ("wake", "shutdown"):
        raise ScheduleValidationError("operation must be wake or shutdown")

    hour = _coerce_int(result.get("hour"), "hour")
    minute = _coerce_int(result.get("minute"), "minute")
    if hour < 0 or hour > 23:
        raise ScheduleValidationError("hour must be between 0 and 23")
    if minute < 0 or minute > 59:
        raise ScheduleValidationError("minute must be between 0 and 59")

    result["hour"] = hour
    result["minute"] = minute
    result["enabled"] = bool(result.get("enabled", True))
    result["days"] = result.get("days", "daily")
    result["weekdays"] = weekdays_for(result)
    result["id"] = str(result.get("id") or f"schedule-{int(time.time() * 1000)}")
    return result


def next_occurrence(schedule: Dict, now: Optional[dt.datetime] = None) -> dt.datetime:
    valid = validate_schedule(schedule)
    if now is None:
        now = dt.datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)

    for offset in range(8):
        day = now.date() + dt.timedelta(days=offset)
        candidate = dt.datetime(
            day.year,
            day.month,
            day.day,
            valid["hour"],
            valid["minute"],
            tzinfo=now.tzinfo,
        )
        if candidate.weekday() in valid["weekdays"] and candidate > now:
            return candidate

    raise ScheduleValidationError("unable to find next occurrence")


def next_wake_timestamp(schedules: Iterable[Dict], now: Optional[dt.datetime] = None) -> Optional[int]:
    candidates = []
    for schedule in schedules:
        valid = validate_schedule(schedule)
        if not valid["enabled"] or valid["operation"] != "wake":
            continue
        candidates.append(next_occurrence(valid, now))
    if not candidates:
        return None
    return int(min(candidates).timestamp())


def next_event(schedules: Iterable[Dict], now: Optional[dt.datetime] = None) -> Optional[Dict]:
    """返回所有启用计划中时间上最近的一次执行（开机或关机）。"""
    best = None
    for schedule in schedules:
        valid = validate_schedule(schedule)
        if not valid["enabled"]:
            continue
        when = next_occurrence(valid, now)
        if best is None or when < best[0]:
            best = (when, valid)
    if best is None:
        return None
    when, valid = best
    return {"id": valid["id"], "operation": valid["operation"], "timestamp": int(when.timestamp())}


def cron_weekday_field(weekdays: List[int]) -> str:
    if weekdays == DAY_PRESETS["daily"]:
        return "*"
    cron_days = sorted(0 if day == 6 else day + 1 for day in weekdays)
    return ",".join(str(day) for day in cron_days)


def cron_line(schedule: Dict) -> Optional[str]:
    valid = validate_schedule(schedule)
    if not valid["enabled"] or valid["operation"] != "shutdown":
        return None
    weekday = cron_weekday_field(valid["weekdays"])
    return f'{valid["minute"]} {valid["hour"]} * * {weekday} {POWER_COMMAND} # autopower:{valid["id"]}'


def strip_managed_crontab(existing: str) -> str:
    lines = existing.splitlines()
    output = []
    skipping = False
    for line in lines:
        if line.strip() == BEGIN_MARKER:
            skipping = True
            continue
        if line.strip() == END_MARKER:
            skipping = False
            continue
        if not skipping:
            output.append(line)
    return "\n".join(output).strip()


def render_managed_crontab(existing: str, schedules: Iterable[Dict]) -> str:
    unmanaged = strip_managed_crontab(existing)
    managed = [line for schedule in schedules for line in [cron_line(schedule)] if line]
    sections = []
    if unmanaged:
        sections.append(unmanaged)
    sections.append("\n".join([BEGIN_MARKER, *managed, END_MARKER]))
    return "\n".join(sections).rstrip() + "\n"


def format_trigger(schedule: Dict) -> str:
    valid = validate_schedule(schedule)
    day_label = {
        "daily": "每天",
        "weekday": "平日",
        "holiday": "假日",
    }.get(valid.get("days"), None)
    if day_label is None:
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        day_label = "、".join(names[day] for day in valid["weekdays"])
    return f'{day_label} {valid["hour"]:02d}:{valid["minute"]:02d}'
