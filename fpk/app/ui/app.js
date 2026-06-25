const state = {
  schedules: [],
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
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

function statusText(status) {
  if (!status) return "";
  const rtc = status.rtc || {};
  const alarm = rtc.alrm_date && rtc.alrm_time ? `${rtc.alrm_date} ${rtc.alrm_time}` : "未读取到 RTC 闹钟";
  return `RTC: ${alarm} · alarm_IRQ: ${rtc.alarm_IRQ || "未知"} · 服务: ${status.systemd || "未知"} · 计划写入: ${status.crontabManaged ? "是" : "否"}`;
}

function setStatus(message, status) {
  statusEl.textContent = status ? `${message} · ${statusText(status)}` : message;
}

function formatShanghaiTime(timestamp) {
  if (!timestamp) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(timestamp * 1000));
}

function operationText(operation) {
  return operation === "wake" ? "开机" : "关机";
}

function formatTrigger(schedule) {
  let label = dayLabels[schedule.days];
  if (!label || schedule.days === "custom") {
    const names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
    label = [...(schedule.weekdays || [])].sort().map((day) => names[day]).join("、") || "指定日期";
  }
  return `${label} ${String(schedule.hour).padStart(2, "0")}:${String(schedule.minute).padStart(2, "0")}`;
}

function nextRunText() {
  const enabled = state.schedules.filter((schedule) => schedule.enabled);
  if (!enabled.length) return "暂无启用计划";
  const first = enabled[0];
  return `${first.trigger || formatTrigger(first)} ${operationText(first.operation)}`;
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
    if (schedule.id === state.selectedId) tr.classList.add("selected");
    tr.addEventListener("click", () => {
      state.selectedId = schedule.id;
      render();
    });

    const enabledTd = document.createElement("td");
    const checkWrap = document.createElement("span");
    checkWrap.className = "cell-inline";
    const checkbox = document.createElement("button");
    checkbox.className = `check ${schedule.enabled ? "checked" : ""}`;
    checkbox.setAttribute("aria-label", "切换启用状态");
    checkbox.addEventListener("click", async (event) => {
      event.stopPropagation();
      await saveSchedule(schedule.id, { ...schedule, enabled: !schedule.enabled });
    });
    checkWrap.append(checkbox);
    enabledTd.append(checkWrap);

    const triggerTd = document.createElement("td");
    triggerTd.textContent = schedule.trigger || formatTrigger(schedule);
    triggerTd.addEventListener("dblclick", () => openModal(schedule.id));

    const operationTd = document.createElement("td");
    const select = document.createElement("select");
    select.className = "select native-select";
    select.append(option("wake", "开机"));
    select.append(option("shutdown", "关机"));
    select.value = schedule.operation;
    select.addEventListener("click", (event) => event.stopPropagation());
    select.addEventListener("change", async () => {
      await saveSchedule(schedule.id, { ...schedule, operation: select.value });
    });
    operationTd.append(select);

    const statusTd = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `badge ${schedule.enabled ? "on" : "off"}`;
    badge.textContent = schedule.enabled ? "已启用" : "已停用";
    statusTd.append(badge);

    tr.append(enabledTd, triggerTd, operationTd, statusTd);
    rowsEl.append(tr);
  });
  updateMetrics();
}

async function loadState() {
  const payload = await requestJson(apiUrl("api/state"));
  state.schedules = payload.schedules;
  if (!state.selectedId && state.schedules[0]) {
    state.selectedId = state.schedules[0].id;
  }
  statusEl.textContent = statusText(payload.status);
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
  };
  modalTitle.textContent = id ? "编辑计划" : "新增计划";
  document.querySelector(`input[name="operation"][value="${schedule.operation}"]`).checked = true;
  setDays(schedule.days || "daily", schedule.weekdays || dayDefaults[schedule.days] || dayDefaults.daily);
  hourSelect.value = String(schedule.hour);
  minuteSelect.value = String(schedule.minute);
  enabledInput.checked = schedule.enabled !== false;
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
  };
}

async function saveModal() {
  const payload = modalPayload();
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
  for (const schedule of state.schedules) {
    await requestJson(apiUrl(`api/schedules/${encodeURIComponent(schedule.id)}`), {
      method: "PUT",
      body: JSON.stringify({ ...schedule, enabled }),
    });
  }
  await loadState();
}

async function applyPlans() {
  setStatus("正在应用计划...");
  try {
    const payload = await requestJson(apiUrl("api/apply"), { method: "POST", body: "{}" });
    const wakeText = payload.nextWake ? `下次开机: ${formatShanghaiTime(payload.nextWake)}` : "未启用开机计划";
    if (payload.ok === false) {
      setStatus(`应用计划失败 · ${wakeText} · ${payload.error || "请检查系统权限"}`, payload.status);
      return;
    }
    setStatus(`计划已应用 · ${wakeText}`, payload.status);
  } catch (error) {
    setStatus(`应用计划失败: ${error.message}`);
  }
}

async function testWake() {
  setStatus("正在测试开机计划...");
  try {
    const payload = await requestJson(apiUrl("api/test-wake"), { method: "POST", body: "{}" });
    const prefix = payload.nextWake ? `下一次开机: ${formatShanghaiTime(payload.nextWake)} (东八区)` : "未启用开机计划";
    if (payload.ok === false) {
      setStatus(`${prefix} · 写入失败: ${payload.error || "请检查 RTC 权限"}`, payload.status);
      return;
    }
    setStatus(prefix, payload.status);
  } catch (error) {
    setStatus(`测试开机计划失败: ${error.message}`);
  }
}

function wireEvents() {
  document.querySelector("#addBtn").addEventListener("click", () => openModal());
  document.querySelector("#emptyAddBtn").addEventListener("click", () => openModal());
  document.querySelector("#editBtn").addEventListener("click", () => {
    const schedule = selectedSchedule();
    if (schedule) openModal(schedule.id);
  });
  document.querySelector("#deleteBtn").addEventListener("click", openConfirm);
  document.querySelector("#enableBtn").addEventListener("click", () => setSelectedEnabled(true));
  document.querySelector("#disableBtn").addEventListener("click", () => setSelectedEnabled(false));
  document.querySelector("#applyBtn").addEventListener("click", applyPlans);
  document.querySelector("#testWakeBtn").addEventListener("click", testWake);
  document.querySelector("#closeModalBtn").addEventListener("click", closeModal);
  document.querySelector("#cancelBtn").addEventListener("click", closeModal);
  document.querySelector("#saveBtn").addEventListener("click", saveModal);
  document.querySelector("#closeConfirmBtn").addEventListener("click", closeConfirm);
  document.querySelector("#cancelDeleteBtn").addEventListener("click", closeConfirm);
  document.querySelector("#confirmDeleteBtn").addEventListener("click", confirmDeleteSelected);
  bulkToggle.addEventListener("click", () => {
    const allEnabled = state.schedules.length > 0 && state.schedules.every((schedule) => schedule.enabled);
    setAllEnabled(!allEnabled);
  });
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
  weekdayMenu.querySelectorAll("[data-days]").forEach((item) => {
    item.addEventListener("click", () => {
      setDays(item.dataset.days, dayDefaults[item.dataset.days] || getWeekdayChecks());
      if (item.dataset.days !== "custom") {
        weekdayMenu.classList.add("hidden");
      }
    });
  });
}

async function boot() {
  initTimeSelects();
  wireEvents();
  try {
    await loadState();
  } catch (error) {
    statusEl.textContent = error.message;
  }
}

boot();
