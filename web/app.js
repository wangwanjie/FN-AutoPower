const state = {
  schedules: [],
  nextEvent: null,
  upcoming: [],
  conflicts: [],
  executor: null,
  selectedId: null,
  editingId: null,
};

const dayDefaults = {
  daily: [0, 1, 2, 3, 4, 5, 6],
  weekday: [0, 1, 2, 3, 4],
  holiday: [5, 6],
};

const dayLabels = {
  daily: "每天",
  weekday: "平日",
  holiday: "假日",
  custom: "指定日期",
};

const rowsEl = document.querySelector("#scheduleRows");
const statusEl = document.querySelector("#statusLine");
const modalOverlay = document.querySelector("#modalBackdrop");
const scheduleModal = document.querySelector("#scheduleModal");
const modalTitle = document.querySelector("#modalTitle");
const confirmDialog = document.querySelector("#confirmDialog");
const confirmMessageEl = document.querySelector("#confirmMessage");
const daysInput = document.querySelector("#daysSelect");
const daysButton = document.querySelector("#daysButton");
const daysButtonText = document.querySelector("#daysButtonText");
const weekdayMenu = document.querySelector("#weekdayMenu");
const hourSelect = document.querySelector("#hourSelect");
const minuteSelect = document.querySelector("#minuteSelect");
const enabledInput = document.querySelector("#enabledInput");
const noteInput = document.querySelector("#noteInput");
const emptyState = document.querySelector("#emptyState");
const tableScroll = document.querySelector("#tableScroll");
const bulkToggle = document.querySelector("#bulkToggle");

function option(value, label = value) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
}

function initTimeSelects() {
  for (let hour = 0; hour < 24; hour += 1) {
    hourSelect.append(option(String(hour), String(hour).padStart(2, "0")));
  }
  for (let minute = 0; minute < 60; minute += 1) {
    minuteSelect.append(option(String(minute), String(minute).padStart(2, "0")));
  }
}

// API 基址：相对当前文档目录解析，使应用在站点根目录（如 http://nas:3868/）
// 与反向代理子路径（如 https://nas.example.com/autopower/）下都能正常请求接口。
const API_ROOT = new URL(".", document.baseURI);
function apiUrl(path) {
  return new URL(String(path).replace(/^\//, ""), API_ROOT).href;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error(response.ok ? "服务返回了无法解析的数据" : `服务不可用（HTTP ${response.status}），请确认应用已启动`);
  }
  if (!response.ok) {
    throw new Error(payload.error || `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}

const executorStateLabels = {
  ok: "运行正常",
  missing: "未部署",
  outdated: "版本过旧",
  error: "运行异常",
};

// 服务端已把 RTC 闹钟换算成真实时刻，这里按本地时间显示，并说明主板时钟的时区偏差
function rtcOffsetText(offset) {
  if (!offset) {
    return "主板时钟为 UTC，已换算为系统时间";
  }
  const sign = offset > 0 ? "快" : "慢";
  const minutes = Math.abs(offset) / 60;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const amount = rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`;
  return `主板时钟比 UTC ${sign} ${amount}，已自动补偿`;
}

function rtcText(executor) {
  const rtc = (executor && executor.rtc) || {};
  if (!rtc.available) {
    return "未读取到 RTC";
  }
  if (!rtc.wake) {
    return `未设置（${rtcOffsetText(rtc.offset)}）`;
  }
  return `${rtc.wakeText}（${rtcOffsetText(rtc.offset)}）`;
}

function historyText(executor) {
  const history = (executor && executor.history) || [];
  if (!history.length) {
    return "暂无记录";
  }
  // 执行器 1.2.0 之前的记录没有 operation 字段，当时只有关机
  return history.slice(0, 3)
    .map((item) => `${item.timeText || item.time} ${operationText(item.operation || "shutdown")}`)
    .join("；");
}

function statusText(executor) {
  if (!executor) {
    return "";
  }
  const label = executorStateLabels[executor.state] || "未知";
  const wake = executor.nextWake ? `RTC 下次开机: ${executor.nextWakeText}` : "未设置开机唤醒";
  return executor.state === "ok" ? `执行器${label} · ${wake}` : `执行器${label}`;
}

function setStatus(message, executor) {
  statusEl.textContent = executor ? `${message} · ${statusText(executor)}` : message;
}

function executorBannerText(executor) {
  if (executor.state === "missing") return "执行器尚未部署：计划已保存，但不会自动开机、关机或重启。";
  if (executor.state === "outdated") return `执行器版本过旧（${executor.version || "未知"}，需要 ${executor.expectedVersion}），请重新执行部署命令。`;
  return `执行器运行异常：${executor.lastError || "未知错误"}`;
}

function renderExecutor() {
  const executor = state.executor;
  const banner = document.querySelector("#executorBanner");
  if (!executor) return;
  banner.classList.toggle("hidden", executor.state === "ok");
  banner.classList.toggle("danger", executor.state === "error");
  document.querySelector("#executorBannerText").textContent = executorBannerText(executor);
  document.querySelector("#deployState").textContent = executorStateLabels[executor.state] || "未知";
  document.querySelector("#deployVersion").textContent = executor.version
    ? `${executor.version}（应用需要 ${executor.expectedVersion}）`
    : `未部署（应用需要 ${executor.expectedVersion}）`;
  document.querySelector("#deployLastRun").textContent = executor.lastRun
    ? `${executor.lastRunText || executor.lastRun}${executor.lastError ? ` · ${executor.lastError}` : ""}`
    : "-";
  document.querySelector("#deployRtc").textContent = rtcText(executor);
  document.querySelector("#deployHistory").textContent = historyText(executor);
  document.querySelector("#deployCommand").textContent = executor.deployCommand;
  document.querySelector("#uninstallCommand").textContent = executor.uninstallCommand;
}

async function copyText(text) {
  if (!text) {
    setStatus("状态尚未加载，请稍后再试");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
  } catch (error) {
    // iframe 或非 HTTPS 环境下 Clipboard API 不可用，退回 execCommand
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  setStatus("命令已复制，请在 SSH 中执行");
}

function openDeploy() {
  renderExecutor();
  modalOverlay.classList.remove("hidden");
  document.querySelector("#deployModal").classList.remove("hidden");
}

function closeDeploy() {
  document.querySelector("#deployModal").classList.add("hidden");
  modalOverlay.classList.add("hidden");
}

const operationLabels = {
  wake: "开机",
  shutdown: "关机",
  reboot: "重启",
};

function operationText(operation) {
  return operationLabels[operation] || operation;
}

function formatTrigger(schedule) {
  let label = dayLabels[schedule.days];
  if (!label || schedule.days === "custom") {
    const names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
    label = [...(schedule.weekdays || [])].sort((a, b) => a - b).map((day) => names[day]).join("、") || "指定日期";
  }
  return `${label} ${String(schedule.hour).padStart(2, "0")}:${String(schedule.minute).padStart(2, "0")}`;
}

function nextRunText() {
  const event = state.nextEvent;
  if (!event) return "暂无启用计划";
  return `${event.localTime} ${operationText(event.operation)}`;
}

function scheduleLabel(id) {
  const schedule = state.schedules.find((item) => item.id === id);
  if (!schedule) {
    return "";
  }
  return schedule.note || schedule.trigger || formatTrigger(schedule);
}

function conflictText(conflicts) {
  const time = (item) => `${String(item.hour).padStart(2, "0")}:${String(item.minute).padStart(2, "0")}`;
  return conflicts.map((item) => {
    const names = item.ids.map(scheduleLabel).filter(Boolean).join("、");
    if (item.kind !== "opposite") {
      return `${time(item)} 存在重复计划（${names}）`;
    }
    // 旧版后端不返回 operations，当时只可能是开机与关机冲突
    const operations = (item.operations || ["wake", "shutdown"]).map(operationText).join("和");
    return `${time(item)} 同时存在${operations}计划（${names}）`;
  }).join("；");
}

function renderConflicts() {
  const banner = document.querySelector("#conflictBanner");
  banner.classList.toggle("hidden", state.conflicts.length === 0);
  document.querySelector("#conflictBannerText").textContent = state.conflicts.length
    ? `计划冲突：${conflictText(state.conflicts)}。请检查是否需要调整。`
    : "";
}

function renderUpcoming() {
  const section = document.querySelector("#upcomingSection");
  const list = document.querySelector("#upcomingList");
  list.innerHTML = "";
  section.classList.toggle("hidden", state.upcoming.length === 0);
  state.upcoming.forEach((event) => {
    const item = document.createElement("li");
    item.className = `upcoming-item ${event.operation}`;
    const time = document.createElement("span");
    time.className = "upcoming-time";
    time.textContent = event.localTime;
    const op = document.createElement("span");
    op.className = `badge op-${event.operation}`;
    op.textContent = operationText(event.operation);
    const label = document.createElement("span");
    label.className = "upcoming-label";
    label.textContent = scheduleLabel(event.id);
    item.append(time, op, label);
    list.append(item);
  });
}

function updateMetrics() {
  document.querySelector("#totalPlans").textContent = String(state.schedules.length);
  document.querySelector("#enabledPlans").textContent = String(state.schedules.filter((item) => item.enabled).length);
  document.querySelector("#nextRun").textContent = nextRunText();
  emptyState.classList.toggle("hidden", state.schedules.length > 0);
  tableScroll.classList.toggle("hidden", state.schedules.length === 0);

  const enabledCount = state.schedules.filter((item) => item.enabled).length;
  bulkToggle.classList.remove("checked", "indeterminate");
  if (enabledCount === state.schedules.length && state.schedules.length > 0) {
    bulkToggle.classList.add("checked");
  } else if (enabledCount > 0) {
    bulkToggle.classList.add("indeterminate");
  }
}

function render() {
  rowsEl.innerHTML = "";
  state.schedules.forEach((schedule) => {
    const tr = document.createElement("tr");
    if (schedule.id === state.selectedId) {
      tr.classList.add("selected");
    }
    tr.addEventListener("click", () => {
      state.selectedId = schedule.id;
      render();
    });
    // 双击整行打开编辑
    tr.addEventListener("dblclick", () => openModal(schedule.id));

    const enabledTd = document.createElement("td");
    const checkWrap = document.createElement("span");
    checkWrap.className = "cell-inline";
    const checkbox = document.createElement("button");
    checkbox.className = `check ${schedule.enabled ? "checked" : ""}`;
    checkbox.setAttribute("aria-label", "切换启用状态");
    checkbox.addEventListener("dblclick", (event) => event.stopPropagation());
    checkbox.addEventListener("click", guarded(async (event) => {
      event.stopPropagation();
      await saveSchedule(schedule.id, { ...schedule, enabled: !schedule.enabled });
    }));
    checkWrap.append(checkbox);
    enabledTd.append(checkWrap);

    const triggerTd = document.createElement("td");
    triggerTd.textContent = schedule.trigger || formatTrigger(schedule);

    const operationTd = document.createElement("td");
    const select = document.createElement("select");
    select.className = "select native-select";
    Object.entries(operationLabels).forEach(([value, label]) => select.append(option(value, label)));
    select.value = schedule.operation;
    select.addEventListener("click", (event) => event.stopPropagation());
    select.addEventListener("dblclick", (event) => event.stopPropagation());
    select.addEventListener("change", guarded(async () => {
      await saveSchedule(schedule.id, { ...schedule, operation: select.value });
    }));
    operationTd.append(select);

    const noteTd = document.createElement("td");
    noteTd.className = "note-cell";
    noteTd.textContent = schedule.note || "-";
    noteTd.title = schedule.note || "";

    const statusTd = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `badge ${schedule.enabled ? "on" : "off"}`;
    badge.textContent = schedule.enabled ? "已启用" : "已停用";
    statusTd.append(badge);

    tr.append(enabledTd, triggerTd, operationTd, noteTd, statusTd);
    rowsEl.append(tr);
  });
  updateMetrics();
  renderConflicts();
  renderUpcoming();
}

async function loadState() {
  const payload = await requestJson(apiUrl("api/state"));
  state.schedules = payload.schedules;
  state.nextEvent = payload.nextEvent || null;
  state.upcoming = payload.upcoming || [];
  state.conflicts = payload.conflicts || [];
  document.querySelector("#serverClock").textContent = payload.serverTime
    ? `NAS 时间 ${payload.serverTime}（${payload.timezone}）`
    : "";
  if (state.selectedId && !state.schedules.some((schedule) => schedule.id === state.selectedId)) {
    state.selectedId = null;
  }
  if (!state.selectedId && state.schedules[0]) {
    state.selectedId = state.schedules[0].id;
  }
  state.executor = payload.executor || null;
  statusEl.textContent = statusText(state.executor);
  renderExecutor();
  render();
}

async function saveSchedule(id, schedule) {
  await requestJson(apiUrl(`api/schedules/${encodeURIComponent(id)}`), {
    method: "PUT",
    body: JSON.stringify(schedule),
  });
  await loadState();
}

function selectedSchedule() {
  return state.schedules.find((schedule) => schedule.id === state.selectedId) || null;
}

function setWeekdayChecks(weekdays) {
  const selected = new Set((weekdays || []).map(String));
  weekdayMenu.querySelectorAll(".weekday-checks input").forEach((input) => {
    input.checked = selected.has(input.value);
  });
}

function getWeekdayChecks() {
  return [...weekdayMenu.querySelectorAll(".weekday-checks input:checked")].map((input) => Number(input.value));
}

function setDays(days, weekdays = dayDefaults[days] || dayDefaults.daily) {
  daysInput.value = days;
  daysButtonText.textContent = dayLabels[days] || "每天";
  setWeekdayChecks(weekdays);
  weekdayMenu.querySelectorAll("[data-days]").forEach((item) => {
    item.classList.toggle("selected", item.dataset.days === days);
  });
}

function openModal(id = null) {
  state.editingId = id;
  const schedule = id ? state.schedules.find((item) => item.id === id) : {
    operation: "wake",
    days: "daily",
    weekdays: dayDefaults.daily,
    hour: 15,
    minute: 0,
    enabled: true,
    note: "",
  };
  modalTitle.textContent = id ? "编辑计划" : "新增计划";
  document.querySelector("#enabledHint").textContent = id ? "启用此计划" : "创建后立即启用此计划";
  document.querySelector(`input[name="operation"][value="${schedule.operation}"]`).checked = true;
  setDays(schedule.days || "daily", schedule.weekdays || dayDefaults[schedule.days] || dayDefaults.daily);
  hourSelect.value = String(schedule.hour);
  minuteSelect.value = String(schedule.minute);
  enabledInput.checked = schedule.enabled !== false;
  noteInput.value = schedule.note || "";
  modalOverlay.classList.remove("hidden");
  scheduleModal.classList.remove("hidden");
}

function closeModal() {
  scheduleModal.classList.add("hidden");
  modalOverlay.classList.add("hidden");
  weekdayMenu.classList.add("hidden");
  state.editingId = null;
}

function modalPayload() {
  const operation = document.querySelector("input[name='operation']:checked").value;
  const days = daysInput.value;
  const weekdays = days === "custom" ? getWeekdayChecks() : dayDefaults[days];
  return {
    enabled: enabledInput.checked,
    operation,
    days,
    weekdays,
    hour: Number(hourSelect.value),
    minute: Number(minuteSelect.value),
    note: noteInput.value.trim(),
  };
}

async function saveModal() {
  const payload = modalPayload();
  if (payload.days === "custom" && payload.weekdays.length === 0) {
    setStatus("请至少选择一个星期");
    return;
  }
  if (state.editingId) {
    const existing = state.schedules.find((schedule) => schedule.id === state.editingId);
    await saveSchedule(state.editingId, { ...existing, ...payload });
  } else {
    const created = await requestJson(apiUrl("api/schedules"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.selectedId = created.id;
    await loadState();
  }
  closeModal();
}

function openConfirm() {
  const schedule = selectedSchedule();
  if (!schedule) return;
  confirmMessageEl.textContent = `删除后将不再按“${schedule.trigger || formatTrigger(schedule)} ${operationText(schedule.operation)}”执行。此操作不会影响其他已保存的开关机规则。`;
  modalOverlay.classList.remove("hidden");
  confirmDialog.classList.remove("hidden");
}

function closeConfirm() {
  confirmDialog.classList.add("hidden");
  modalOverlay.classList.add("hidden");
}

async function confirmDeleteSelected() {
  const schedule = selectedSchedule();
  if (!schedule) {
    closeConfirm();
    return;
  }
  await requestJson(apiUrl(`api/schedules/${encodeURIComponent(schedule.id)}`), { method: "DELETE" });
  state.selectedId = null;
  closeConfirm();
  await loadState();
}

async function setSelectedEnabled(enabled) {
  const schedule = selectedSchedule();
  if (!schedule) return;
  await saveSchedule(schedule.id, { ...schedule, enabled });
}

async function setAllEnabled(enabled) {
  // 服务端一次性修改全部计划，避免逐条请求时中途失败留下部分启用的状态
  await requestJson(apiUrl("api/schedules"), {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
  await loadState();
}

function anyDialogOpen() {
  return !modalOverlay.classList.contains("hidden");
}

function closeAllDialogs() {
  if (!weekdayMenu.classList.contains("hidden")) {
    weekdayMenu.classList.add("hidden");
    return;
  }
  if (!scheduleModal.classList.contains("hidden")) {
    closeModal();
  } else if (!confirmDialog.classList.contains("hidden")) {
    closeConfirm();
  } else if (!document.querySelector("#deployModal").classList.contains("hidden")) {
    closeDeploy();
  }
}

// 包装异步事件处理：任何接口失败都在底部状态栏提示，而不是静默吞掉。
function guarded(handler) {
  return async (...args) => {
    try {
      await handler(...args);
    } catch (error) {
      setStatus(`操作失败: ${error.message}`);
    }
  };
}

function wireEvents() {
  document.querySelector("#addBtn").addEventListener("click", () => openModal());
  document.querySelector("#emptyAddBtn").addEventListener("click", () => openModal());
  document.querySelector("#editBtn").addEventListener("click", () => {
    const schedule = selectedSchedule();
    if (schedule) openModal(schedule.id);
  });
  document.querySelector("#deleteBtn").addEventListener("click", openConfirm);
  document.querySelector("#enableBtn").addEventListener("click", guarded(() => setSelectedEnabled(true)));
  document.querySelector("#disableBtn").addEventListener("click", guarded(() => setSelectedEnabled(false)));
  document.querySelector("#deployBtn").addEventListener("click", openDeploy);
  document.querySelector("#bannerDeployBtn").addEventListener("click", openDeploy);
  document.querySelector("#closeDeployBtn").addEventListener("click", closeDeploy);
  document.querySelector("#doneDeployBtn").addEventListener("click", guarded(async () => {
    closeDeploy();
    await loadState();
  }));
  document.querySelector("#refreshDeployBtn").addEventListener("click", guarded(loadState));
  document.querySelector("#copyDeployBtn").addEventListener("click", () => copyText(state.executor.deployCommand));
  document.querySelector("#copyUninstallBtn").addEventListener("click", () => copyText(state.executor.uninstallCommand));
  document.querySelector("#closeModalBtn").addEventListener("click", closeModal);
  document.querySelector("#cancelBtn").addEventListener("click", closeModal);
  document.querySelector("#saveBtn").addEventListener("click", guarded(saveModal));
  document.querySelector("#closeConfirmBtn").addEventListener("click", closeConfirm);
  document.querySelector("#cancelDeleteBtn").addEventListener("click", closeConfirm);
  document.querySelector("#confirmDeleteBtn").addEventListener("click", guarded(confirmDeleteSelected));
  bulkToggle.addEventListener("click", guarded(async () => {
    const allEnabled = state.schedules.length > 0 && state.schedules.every((schedule) => schedule.enabled);
    await setAllEnabled(!allEnabled);
  }));
  daysButton.addEventListener("click", () => {
    weekdayMenu.classList.toggle("hidden");
  });
  document.addEventListener("click", (event) => {
    if (weekdayMenu.classList.contains("hidden")) return;
    if (weekdayMenu.contains(event.target) || daysButton.contains(event.target)) return;
    weekdayMenu.classList.add("hidden");
  });
  modalOverlay.addEventListener("click", () => {
    if (!weekdayMenu.classList.contains("hidden")) {
      weekdayMenu.classList.add("hidden");
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && anyDialogOpen()) {
      closeAllDialogs();
    }
  });
  weekdayMenu.querySelectorAll("[data-days]").forEach((item) => {
    item.addEventListener("click", () => {
      setDays(item.dataset.days, dayDefaults[item.dataset.days] || getWeekdayChecks());
      if (item.dataset.days !== "custom") {
        weekdayMenu.classList.add("hidden");
      }
    });
  });
}

// 定时刷新执行器状态与下次执行时间；页面不可见或弹窗打开时跳过，避免打断编辑
const REFRESH_INTERVAL_MS = 30000;

function startAutoRefresh() {
  setInterval(() => {
    if (document.hidden || anyDialogOpen()) {
      return;
    }
    loadState().catch((error) => setStatus(`刷新失败: ${error.message}`));
  }, REFRESH_INTERVAL_MS);
}

async function boot() {
  initTimeSelects();
  wireEvents();
  try {
    await loadState();
  } catch (error) {
    setStatus(`加载失败: ${error.message}`);
  }
  startAutoRefresh();
}

boot();
