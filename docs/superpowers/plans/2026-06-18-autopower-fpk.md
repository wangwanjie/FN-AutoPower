# AutoPower FPK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Feiniu/fnOS FPK application that manages Synology-style automatic power-on and shutdown schedules.

**Architecture:** Use a script-based FPK package with Python standard-library backend and static HTML/CSS/JS frontend. Core scheduling logic is pure Python and tested locally; system writes are isolated in a runtime adapter that calls crontab, systemctl, and RTC wakealarm.

**Tech Stack:** Python 3 standard library, static HTML/CSS/JavaScript, shell scripts, fnOS FPK package metadata.

---

### Task 1: Core Schedule Engine

**Files:**
- Create: `src/autopower_core.py`
- Create: `tests/test_autopower_core.py`

- [ ] **Step 1: Write tests for next wake and cron rendering**

Create tests that verify daily and weekday wake calculation and managed crontab rendering.

- [ ] **Step 2: Run tests and confirm they fail before implementation**

Run: `python3 -m unittest tests/test_autopower_core.py -v`

Expected: import failure for missing `src.autopower_core`.

- [ ] **Step 3: Implement schedule model and rendering**

Implement validation, next occurrence calculation, next wake selection, and managed crontab rendering.

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests/test_autopower_core.py -v`

Expected: all tests pass.

### Task 2: Runtime Backend

**Files:**
- Create: `src/autopower_server.py`
- Create: `tests/test_autopower_server.py`

- [ ] **Step 1: Write tests for local API helpers**

Test state file loading, schedule creation, and update validation without starting privileged system writes.

- [ ] **Step 2: Run tests and confirm they fail before implementation**

Run: `python3 -m unittest tests/test_autopower_server.py -v`

Expected: import failure or missing function failure.

- [ ] **Step 3: Implement HTTP server and system adapter**

Add JSON API routes, static file serving, state persistence, crontab update, RTC write, and systemd service installation helpers.

- [ ] **Step 4: Run backend tests**

Run: `python3 -m unittest tests/test_autopower_server.py -v`

Expected: all tests pass.

### Task 3: Synology-Style GUI

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`
- Create: `web/app.js`

- [ ] **Step 1: Implement the table and modal**

Build a native static UI matching the supplied screenshots: tabs, toolbar, schedule table, enabled checkboxes, operation selects, modal radios, date dropdown, weekday checklist, hour/minute selects, and footer actions.

- [ ] **Step 2: Wire API calls**

Connect load, add, edit, delete, enable toggle, operation update, apply, and test-wake interactions to the backend API.

- [ ] **Step 3: Run syntax checks**

Run: `python3 -m json.tool` only where JSON files are present, and use a local static server check if needed.

### Task 4: FPK Package Structure

**Files:**
- Create: `fpk/manifest`
- Create: `fpk/config/privilege`
- Create: `fpk/config/resource`
- Create: `fpk/cmd/main`
- Create: `fpk/app/AutoPower/src/autopower_core.py`
- Create: `fpk/app/AutoPower/src/autopower_server.py`
- Create: `fpk/app/AutoPower/web/index.html`
- Create: `fpk/app/AutoPower/web/styles.css`
- Create: `fpk/app/AutoPower/web/app.js`
- Create: `fpk/app/ui/config`
- Create: `scripts/sync-fpk.sh`
- Create: `scripts/build-fpk.sh`

- [ ] **Step 1: Create FPK metadata**

Use package name `autopower`, display name `自动开关机`, x86_64 architecture, root/package privilege as needed, and a URL desktop entry on port 3868.

- [ ] **Step 2: Add command script**

Implement `start`, `stop`, and `status` commands that manage the Python server process and expose app status.

- [ ] **Step 3: Add sync and build scripts**

Copy source files into `fpk/app/AutoPower` and invoke `fnpack` when available.

### Task 5: Verification and Handoff

**Files:**
- Modify as needed based on test output

- [ ] **Step 1: Run full local verification**

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile src/autopower_core.py src/autopower_server.py
./scripts/sync-fpk.sh
```

- [ ] **Step 2: Document manual fnOS verification**

Include commands to install or inspect the FPK, check service status, check crontab managed lines, and check `/proc/driver/rtc`.
