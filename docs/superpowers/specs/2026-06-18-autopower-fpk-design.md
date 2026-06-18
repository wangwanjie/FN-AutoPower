# AutoPower FPK Design

## Goal

Build a Feiniu/fnOS FPK application named AutoPower that provides a Synology-style power schedule GUI for automatic power-on and shutdown plans.

## User Experience

The app opens as a utility page with tabs styled like Synology Control Panel. The active tab is "开关机计划管理". It shows a toolbar with "新增", "编辑", "删除", and "计划管理总览". Below it is a table with:

- a selection column
- enabled checkbox
- trigger time such as "每天 15:00" or "周五 14:30"
- operation selector showing "开机" or "关机"

Add and edit open a modal titled "编辑计划管理". The modal contains:

- radio options for "开机" and "关机"
- a date selector with "每天", "假日", "平日", and individual weekdays
- hour and minute selectors
- the RTC wake note from Synology for power-on plans
- "取消" and "确定" actions

The first version supports "每天", "平日", "假日", and custom weekday combinations. "假日" maps to Saturday and Sunday.

## System Behavior

The app stores plans in `/var/packages/autopower/var/schedules.json` by default, or `AUTOPOWER_DATA_DIR` during local development and tests.

When plans are applied:

- enabled shutdown plans are written to root crontab as managed lines
- enabled wake plans are used to compute the next upcoming RTC wake time
- a systemd service runs before shutdown and sets the next RTC alarm again
- power-on uses `/sys/class/rtc/rtc0/wakealarm`
- shutdown uses `/sbin/poweroff`

The app preserves unmanaged crontab lines by wrapping its own entries between markers:

```text
# BEGIN AUTOPOWER
# END AUTOPOWER
```

For multiple enabled wake plans, the next matching local time is selected and written to RTC. This mirrors the tested shell script but extends it to multiple weekly rules.

## Architecture

The package is script-based rather than Docker-based so it can operate directly on the host RTC, systemd, and root crontab.

Files:

- `src/autopower_core.py`: pure schedule model, validation, next wake calculation, cron rendering, status parsing
- `src/autopower_server.py`: Python standard-library HTTP API and static file server
- `web/`: static Synology-style UI
- `fpk/`: FPK manifest, privilege/resource config, command script, install scripts, and packaged app files
- `scripts/build-fpk.sh`: invokes `fnpack` when available
- `tests/`: Python unit tests for the behavior that can be verified locally

## API

The local HTTP API exposes:

- `GET /api/state`: returns schedules and system status
- `POST /api/schedules`: creates a plan
- `PUT /api/schedules/{id}`: updates a plan
- `DELETE /api/schedules/{id}`: removes a plan
- `POST /api/apply`: writes system configuration
- `POST /api/test-wake`: computes and writes the current next wake plan

## Safety

The implementation never deletes unmanaged crontab content. It validates schedule time and weekday data before writing any system state. If system commands fail, API responses include the command error.

## Verification

Local verification uses Python unit tests for schedule calculation and cron rendering, plus a syntax check for Python modules. System integration must be verified on fnOS because `/sys/class/rtc/rtc0/wakealarm`, root crontab, and systemd are host-specific.
