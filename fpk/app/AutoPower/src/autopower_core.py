import datetime as dt
import time
from typing import Dict, Iterable, List, Optional


# 1.1.x 写入 root crontab 的托管区标记，执行器部署时据此清理旧任务
BEGIN_MARKER = "# BEGIN AUTOPOWER"
END_MARKER = "# END AUTOPOWER"

DAY_PRESETS = {
    "daily": [0, 1, 2, 3, 4, 5, 6],
    "weekday": [0, 1, 2, 3, 4],
    "holiday": [5, 6],
}


# 备注的最大长度，超出部分拒绝保存
NOTE_MAX_LENGTH = 40


# 计划支持的操作：开机由 RTC 唤醒完成，关机、重启由执行器在命中的那一分钟执行
OPERATIONS = ("wake", "shutdown", "reboot")


class ScheduleValidationError(ValueError):
    pass


def _coerce_int(value, field: str) -> int:
    # bool 是 int 的子类，True 会被当成 1，必须单独拒绝；小数也不能被静默截断
    if isinstance(value, bool):
        raise ScheduleValidationError(f"{field} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ScheduleValidationError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleValidationError(f"{field} must be an integer") from exc


def _coerce_note(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ScheduleValidationError("note must be a string")
    note = " ".join(value.split())
    if len(note) > NOTE_MAX_LENGTH:
        raise ScheduleValidationError(f"note must be at most {NOTE_MAX_LENGTH} characters")
    return note


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
    """校验并规范化一条计划，只保留已知字段。

    前端回传的对象可能带有 trigger 等展示字段，白名单可以避免这些字段被写进计划文件。
    """
    if not isinstance(schedule, dict):
        raise ScheduleValidationError("schedule must be an object")
    operation = schedule.get("operation")
    if operation not in OPERATIONS:
        raise ScheduleValidationError("operation must be wake, shutdown, or reboot")

    hour = _coerce_int(schedule.get("hour"), "hour")
    minute = _coerce_int(schedule.get("minute"), "minute")
    if hour < 0 or hour > 23:
        raise ScheduleValidationError("hour must be between 0 and 23")
    if minute < 0 or minute > 59:
        raise ScheduleValidationError("minute must be between 0 and 59")

    enabled = schedule.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ScheduleValidationError("enabled must be a boolean")

    days = schedule.get("days", "daily")
    return {
        "id": str(schedule.get("id") or f"schedule-{int(time.time() * 1000)}"),
        "enabled": enabled,
        "operation": operation,
        "days": days,
        "weekdays": weekdays_for({"days": days, "weekdays": schedule.get("weekdays", [])}),
        "hour": hour,
        "minute": minute,
        "note": _coerce_note(schedule.get("note")),
    }


def _local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _resolve_now(now: Optional[dt.datetime]):
    """返回 (带时区的 now, 时区)。时区为 None 表示按系统时区逐个换算候选时刻。"""
    if now is None:
        return _local_now(), None
    if now.tzinfo is None:
        return now.astimezone(), None
    return now, now.tzinfo


def _at(day: dt.date, hour: int, minute: int, tzinfo) -> dt.datetime:
    if tzinfo is None:
        # 不带时区的墙上时间按系统时区解释，得到该日期实际生效的偏移（跨夏令时也正确）
        return dt.datetime(day.year, day.month, day.day, hour, minute).astimezone()
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tzinfo)


def next_occurrence(schedule: Dict, now: Optional[dt.datetime] = None) -> dt.datetime:
    """计划在 now 之后的下一次触发时刻。

    now 为 None 或不带时区时按系统时区计算，每个候选时刻单独换算偏移，跨夏令时切换也正确；
    now 带时区时（测试或指定时区）按该固定时区计算。
    """
    valid = validate_schedule(schedule)
    now, tzinfo = _resolve_now(now)

    for offset in range(8):
        day = now.date() + dt.timedelta(days=offset)
        candidate = _at(day, valid["hour"], valid["minute"], tzinfo)
        if day.weekday() in valid["weekdays"] and candidate > now:
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
    """返回所有启用计划中时间上最近的一次执行（开机、关机或重启）。"""
    best = None
    for schedule in schedules:
        valid = validate_schedule(schedule)
        if not valid["enabled"]:
            continue
        # 同一时刻按 OPERATIONS 顺序取，与未来执行预览的排序一致
        key = (next_occurrence(valid, now), OPERATIONS.index(valid["operation"]))
        if best is None or key < best[0]:
            best = (key, valid)
    if best is None:
        return None
    (when, _), valid = best
    return {"id": valid["id"], "operation": valid["operation"], "timestamp": int(when.timestamp())}


def upcoming_events(schedules: Iterable[Dict], now: Optional[dt.datetime] = None, days: int = 7, limit: int = 20) -> List[Dict]:
    """未来 days 天内所有启用计划的触发时刻，按时间排序，最多 limit 条。"""
    now, tzinfo = _resolve_now(now)
    end = now + dt.timedelta(days=days)
    events = []
    for schedule in schedules:
        valid = validate_schedule(schedule)
        if not valid["enabled"]:
            continue
        for offset in range(days + 1):
            day = now.date() + dt.timedelta(days=offset)
            if day.weekday() not in valid["weekdays"]:
                continue
            when = _at(day, valid["hour"], valid["minute"], tzinfo)
            if now < when <= end:
                events.append({"id": valid["id"], "operation": valid["operation"], "timestamp": int(when.timestamp())})
    # 同一时刻按开机、关机、重启排序，与执行器的处理顺序无关，只为展示稳定
    events.sort(key=lambda item: (item["timestamp"], OPERATIONS.index(item["operation"]), item["id"]))
    return events[:limit]


def find_conflicts(schedules: Iterable[Dict]) -> List[Dict]:
    """找出启用计划之间的冲突：同一星期同一分钟存在不同操作（如既开机又关机、既关机又重启），
    或者重复的同类计划。operations 按 OPERATIONS 顺序列出该时刻涉及的操作。"""
    slots = {}
    for schedule in schedules:
        valid = validate_schedule(schedule)
        if not valid["enabled"]:
            continue
        for weekday in valid["weekdays"]:
            slots.setdefault((weekday, valid["hour"], valid["minute"]), []).append(valid)

    conflicts = []
    seen = set()
    for (_, hour, minute), items in sorted(slots.items()):
        operations = {item["operation"] for item in items}
        ids = tuple(sorted({item["id"] for item in items}))
        if len(ids) < 2:
            continue
        kind = "opposite" if len(operations) > 1 else "duplicate"
        key = (kind, hour, minute, ids)
        if key in seen:
            continue
        seen.add(key)
        ordered = [operation for operation in OPERATIONS if operation in operations]
        conflicts.append({"kind": kind, "hour": hour, "minute": minute, "ids": list(ids), "operations": ordered})
    return conflicts


# 时区偏移都是 15 分钟的整数倍，RTC 与系统时钟的偏差按此取整，忽略秒级漂移
RTC_OFFSET_STEP = 15 * 60


def rtc_offset(rtc_epoch: int, system_epoch: int) -> int:
    """RTC 读数（内核按 UTC 解释的秒数）相对系统时钟的偏差，取整到 15 分钟。

    RTC 走 UTC 时为 0；RTC 走北京时间（本地时间）时约为 +28800。
    """
    return round((rtc_epoch - system_epoch) / RTC_OFFSET_STEP) * RTC_OFFSET_STEP


def rtc_alarm_value(timestamp: int, offset: int) -> int:
    """写入 sysfs wakealarm 的值：真实唤醒时刻加上 RTC 偏差，RTC 读数到达该值时才是目标时刻。"""
    return timestamp + offset


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
