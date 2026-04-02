const state = {
  projectId: "",
  project: null,
  sessions: [],
  currentSession: null,
  versions: [],
  ui: {
    busy: false,
    timer: null,
    progress: 0,
    autoProgressCap: 88,
  },
};

const PRIMARY_ACTION_BUSY_LABELS = {
  "submit-answer": "AI思考中...",
  "skip-question": "跳过处理中...",
  "finish-session": "处理中...",
};

document.addEventListener("DOMContentLoaded", () => {
  setupGlobalErrorHandlers();
  state.projectId = new URLSearchParams(window.location.search).get("project_id") || "";

  bindStaticActions();
  initializeStatusUi();

  if (!state.projectId) {
    showMessage("缺少 project_id，无法进入项目工作区", true);
    return;
  }

  bootstrap().catch((error) => {
    reportError("初始化", error);
  });
});

function bindStaticActions() {
  document.getElementById("go-home").addEventListener("click", () => {
    window.location.href = "/";
  });
  document.getElementById("go-settings").addEventListener("click", () => {
    window.location.href = "/settings";
  });

  document.getElementById("open-folder-btn").addEventListener("click", withErrorHandling("打开项目文件夹", openFolder));
  document
    .getElementById("proactive-push-use-global")
    .addEventListener("change", applyProactiveControlsState);
  document.getElementById("create-session").addEventListener("click", withErrorHandling("新建会话", createSession));
  document.getElementById("rename-session").addEventListener("click", withErrorHandling("重命名会话", renameSession));
  document.getElementById("delete-session").addEventListener("click", withErrorHandling("删除会话", deleteSession));
  document
    .getElementById("submit-answer")
    .addEventListener("click", withErrorHandling("提交回答", async () => submitAnswer(false)));
  document
    .getElementById("skip-question")
    .addEventListener("click", withErrorHandling("跳过问题", async () => submitAnswer(true)));
  document
    .getElementById("finish-session")
    .addEventListener("click", withErrorHandling("保存对话并生成Agent开发文档", finishSession));
  document
    .getElementById("save-project-settings")
    .addEventListener("click", withErrorHandling("保存项目设置", saveProjectSettings));
  document
    .getElementById("pick-project-folder-path")
    .addEventListener("click", withErrorHandling("选择项目目录", onPickProjectFolderPath));
  document
    .getElementById("pick-project-doc-folder")
    .addEventListener("click", withErrorHandling("选择项目开发文档目录", onPickProjectDocFolder));
  document.getElementById("view-version").addEventListener("click", withErrorHandling("查看版本", viewVersion));
  document.getElementById("compare-version").addEventListener("click", withErrorHandling("对比版本", compareVersion));
  document.getElementById("restore-version").addEventListener("click", withErrorHandling("恢复版本", restoreVersion));
}

async function bootstrap() {
  await loadProject();
  await loadVersions();

  if (state.sessions.length > 0) {
    await loadSession(state.sessions[0].id);
  } else {
    renderSessionView();
  }
}

async function loadProject() {
  state.project = await api(`/api/projects/${encodeURIComponent(state.projectId)}`);
  state.sessions = state.project.sessions || [];

  renderProjectHeader();
  renderSessions();
  applyProjectSettingsToForm();
}

function renderProjectHeader() {
  const title = document.getElementById("project-title");
  const subtitle = document.getElementById("project-subtitle");

  title.textContent = `DocAgent · ${state.project.name}`;
  subtitle.textContent = state.project.project_doc_exists
    ? `项目开发文档已就绪：${state.project.project_doc_path}`
    : `项目开发文档缺失：${state.project.project_doc_path}（不影响继续使用）`;
}

function applyProjectSettingsToForm() {
  document.getElementById("project-name-input").value = state.project.name || "";
  document.getElementById("project-doc-path").value = state.project.project_doc_path || "";
  document.getElementById("project-folder-path").value = state.project.folder || "";

  const useGlobal = Boolean(state.project.proactive_push_use_global);
  document.getElementById("proactive-push-use-global").checked = useGlobal;
  document.getElementById("proactive-push-enabled").checked = Boolean(state.project.proactive_push_enabled);
  document.getElementById("proactive-push-branch").value = state.project.proactive_push_branch || "";
  applyProactiveControlsState();
}

function applyProactiveControlsState() {
  const useGlobal = document.getElementById("proactive-push-use-global").checked;
  document.getElementById("proactive-push-enabled").disabled = useGlobal;
  document.getElementById("proactive-push-branch").disabled = useGlobal;
}

function renderSessions() {
  const container = document.getElementById("session-list");
  container.innerHTML = "";

  if (!state.sessions.length) {
    container.innerHTML = '<div class="session-item"><p>暂无会话，点击“新建会话”。</p></div>';
    return;
  }

  for (const session of state.sessions) {
    const card = document.createElement("div");
    card.className = "session-item";
    if (state.currentSession && state.currentSession.id === session.id) {
      card.classList.add("active");
    }

    card.innerHTML = `
      <h4>${escapeHtml(session.name)}</h4>
      <p>更新时间：${escapeHtml(session.updated_at || "-")}</p>
      <p>状态：${session.is_complete ? "已完成" : "进行中"}</p>
    `;
    card.addEventListener("click", withErrorHandling("加载会话", async () => loadSession(session.id)));
    container.appendChild(card);
  }
}

async function createSession() {
  const name = window.prompt("输入会话名称（可留空自动命名）", "");
  const payload = name === null ? {} : { name: name.trim() };

  const created = await api(`/api/projects/${encodeURIComponent(state.projectId)}/sessions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  await loadProject();
  await loadVersions();
  await loadSession(created.id);
  showMessage("会话已创建，请先直接输入你的需求。", false);
}

async function renameSession() {
  if (!state.currentSession) {
    showMessage("请先选择会话", true);
    return;
  }

  const name = window.prompt("新的会话名称", state.currentSession.name || "");
  if (name === null) {
    return;
  }
  if (!name.trim()) {
    showMessage("会话名称不能为空", true);
    return;
  }

  await api(
    `/api/projects/${encodeURIComponent(state.projectId)}/sessions/${encodeURIComponent(state.currentSession.id)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ name: name.trim() }),
    }
  );

  await loadProject();
  await loadSession(state.currentSession.id);
  showMessage("会话已重命名", false);
}

async function deleteSession() {
  if (!state.currentSession) {
    showMessage("请先选择会话", true);
    return;
  }

  const confirmed = window.confirm("确认删除当前会话？");
  if (!confirmed) {
    return;
  }

  await api(
    `/api/projects/${encodeURIComponent(state.projectId)}/sessions/${encodeURIComponent(state.currentSession.id)}`,
    {
      method: "DELETE",
    }
  );

  state.currentSession = null;
  await loadProject();
  await loadVersions();
  if (state.sessions.length > 0) {
    await loadSession(state.sessions[0].id);
  } else {
    renderSessionView();
  }
  showMessage("会话已删除", false);
}

async function loadSession(sessionId) {
  const session = await api(
    `/api/projects/${encodeURIComponent(state.projectId)}/sessions/${encodeURIComponent(sessionId)}`
  );

  state.currentSession = session;
  renderSessions();
  renderSessionView();
  selectCurrentVersion();
}

function renderSessionView() {
  const questionText = document.getElementById("question-text");
  const unresolvedList = document.getElementById("unresolved-list");
  const historyList = document.getElementById("history-list");
  const optionsList = document.getElementById("options-list");

  unresolvedList.innerHTML = "";
  historyList.innerHTML = "";
  optionsList.innerHTML = "";

  if (!state.currentSession) {
    questionText.textContent = "请先选择或创建一个会话。";
    renderDocPreview("");
    renderDiffPreview("");
    return;
  }

  questionText.textContent = state.currentSession.current_question?.question || "请继续补充需求";
  renderOptions(state.currentSession.current_question?.options || []);

  const unresolved = state.currentSession.unresolved_points || [];
  if (!unresolved.length) {
    const li = document.createElement("li");
    li.textContent = state.currentSession.ai_thinks_clear
      ? "当前轮次 AI 未发现新的歧义点。"
      : "当前无待澄清项，提交输入后由 AI 继续识别。";
    unresolvedList.appendChild(li);
  } else {
    for (const item of unresolved) {
      const li = document.createElement("li");
      li.textContent = item;
      unresolvedList.appendChild(li);
    }
  }

  const history = state.currentSession.history || [];
  const recent = history.slice().reverse();
  for (const turn of recent) {
    const li = document.createElement("li");
    li.textContent = `${turn.question || ""} | ${turn.answer || ""}`;
    historyList.appendChild(li);
  }

  renderDocPreview(state.currentSession.current_document || "");
  renderDiffPreview("");
  document.getElementById("extra-input").value = "";
  updateExtraLabel();
}

function renderOptions(options) {
  const list = document.getElementById("options-list");
  list.innerHTML = "";

  options.forEach((option, index) => {
    const label = document.createElement("label");
    label.className = "option-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "question-option";
    checkbox.value = option;
    checkbox.id = `opt-${index}`;
    checkbox.addEventListener("change", updateExtraLabel);

    const span = document.createElement("span");
    span.textContent = option;

    label.appendChild(checkbox);
    label.appendChild(span);
    list.appendChild(label);
  });
}

function updateExtraLabel() {
  const optionCount = document.querySelectorAll('input[name="question-option"]').length;
  const checkedCount = document.querySelectorAll('input[name="question-option"]:checked').length;
  const label = document.getElementById("extra-label");
  const input = document.getElementById("extra-input");

  if (optionCount === 0) {
    label.textContent = "需求描述：";
    input.placeholder = "请直接描述你的需求，重点写清目标、用户、输入输出和约束";
    return;
  }

  label.textContent = checkedCount > 0 ? "补充：" : "其他：";
  input.placeholder = checkedCount > 0 ? "可继续补充细节（可选）" : "若选项都不准确，可直接描述";
}

async function submitAnswer(skipQuestion) {
  if (!state.currentSession) {
    showMessage("请先选择会话", true);
    return;
  }

  const selectedOptions = Array.from(
    document.querySelectorAll('input[name="question-option"]:checked')
  ).map((item) => item.value);
  const textInput = document.getElementById("extra-input").value.trim();

  if (!skipQuestion && selectedOptions.length === 0 && !textInput) {
    showMessage("请至少选择一个选项或填写补充内容", true);
    return;
  }

  const payload = {
    selected_options: selectedOptions,
    text_input: textInput,
    skip_question: skipQuestion,
  };

  const startText = skipQuestion
    ? "AI思考中...正在跳过该问题并重新评估需求"
    : "AI思考中...正在分析回答并识别澄清点";
  const successText = skipQuestion ? "已跳过该问题并更新会话。" : "回答已提交并生成新版本。";

  const executed = await runWithGlobalStatus(
    {
      startText,
      successText,
      errorTextPrefix: "AI处理失败：",
      autoCap: 90,
    },
    async (updateProgress) => {
      updateProgress(14, "正在提交输入给AI...");
      const response = await api(
        `/api/projects/${encodeURIComponent(state.projectId)}/sessions/${encodeURIComponent(state.currentSession.id)}/answer`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      );

      updateProgress(68, "AI返回完成，正在同步会话与项目信息...");
      state.currentSession = response.session;
      await loadProject();

      updateProgress(84, "正在刷新文档版本...");
      await loadVersions();
      renderSessions();
      renderSessionView();
      selectCurrentVersion();
      updateProgress(96, "即将完成...");
    }
  );

  if (!executed) {
    return;
  }
  showMessage(successText, false);
}

async function finishSession() {
  if (!state.currentSession) {
    showMessage("请先选择会话", true);
    return;
  }

  const executed = await runWithGlobalStatus(
    {
      startText: "正在保存对话并生成Agent开发文档...",
      successText: "保存完成，Agent开发文档已更新。",
      errorTextPrefix: "保存失败：",
      autoCap: 92,
    },
    async (updateProgress) => {
      updateProgress(18, "正在提交保存请求...");
      const result = await api(
        `/api/projects/${encodeURIComponent(state.projectId)}/sessions/${encodeURIComponent(state.currentSession.id)}/finish`,
        {
          method: "POST",
        }
      );

      updateProgress(70, "正在刷新项目信息...");
      state.currentSession = result;
      await loadProject();

      updateProgress(86, "正在刷新版本列表...");
      await loadVersions();
      renderSessions();
      renderSessionView();
      updateProgress(96, "即将完成...");
    }
  );

  if (!executed) {
    return;
  }
  showMessage("会话已保存，并已生成Agent开发文档。", false);
}

async function loadVersions() {
  state.versions = await api(`/api/projects/${encodeURIComponent(state.projectId)}/doc/versions`);
  const select = document.getElementById("version-select");
  select.innerHTML = "";

  if (!state.versions.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无版本";
    select.appendChild(option);
    return;
  }

  for (const version of state.versions) {
    const option = document.createElement("option");
    option.value = version.file_name;
    option.textContent = `${version.file_name} (${version.updated_at})`;
    select.appendChild(option);
  }
}

function selectCurrentVersion() {
  if (!state.currentSession) {
    return;
  }
  const select = document.getElementById("version-select");
  if (!select || !state.currentSession.current_version) {
    return;
  }

  const exists = state.versions.some((item) => item.file_name === state.currentSession.current_version);
  if (exists) {
    select.value = state.currentSession.current_version;
  }
}

async function viewVersion() {
  const select = document.getElementById("version-select");
  const version = select.value;
  if (!version) {
    showMessage("没有可查看的版本", true);
    return;
  }

  const data = await api(
    `/api/projects/${encodeURIComponent(state.projectId)}/doc/versions/${encodeURIComponent(version)}`
  );
  renderDocPreview(data.content || "");
  renderDiffPreview("");
  showMessage(`已查看版本：${version}`, false);
}

async function compareVersion() {
  const select = document.getElementById("version-select");
  const version = select.value;
  if (!version) {
    showMessage("没有可对比的版本", true);
    return;
  }

  const data = await api(
    `/api/projects/${encodeURIComponent(state.projectId)}/doc/compare?source=${encodeURIComponent(version)}&target=DEVELOPMENT.md`
  );
  renderDiffPreview(data.diff || "# 无差异");
  showMessage(`已对比版本：${version} 与 DEVELOPMENT.md`, false);
}

async function restoreVersion() {
  const select = document.getElementById("version-select");
  const version = select.value;
  if (!version) {
    showMessage("没有可恢复的版本", true);
    return;
  }

  const confirmed = window.confirm("确认恢复为该版本？这会覆盖 DEVELOPMENT.md。\n" + version);
  if (!confirmed) {
    return;
  }

  const payload = {
    session_id: state.currentSession?.id || null,
  };

  const data = await api(
    `/api/projects/${encodeURIComponent(state.projectId)}/doc/versions/${encodeURIComponent(version)}/restore`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );

  if (state.currentSession) {
    state.currentSession.current_document = data.content || "";
    state.currentSession.current_version = version;
  }

  renderDocPreview(data.content || "");
  renderDiffPreview("");
  showMessage(`已恢复版本：${version}`, false);
}

async function saveProjectSettings() {
  const projectName = document.getElementById("project-name-input").value.trim();
  const projectDocPath = document.getElementById("project-doc-path").value.trim();
  const projectFolderPath = document.getElementById("project-folder-path").value.trim();
  const proactivePushUseGlobal = document.getElementById("proactive-push-use-global").checked;
  const proactivePushEnabled = document.getElementById("proactive-push-enabled").checked;
  const proactivePushBranch = document.getElementById("proactive-push-branch").value.trim();

  const payload = {};
  if (projectName) {
    payload.name = projectName;
  }
  if (projectDocPath) {
    payload.project_doc_path = projectDocPath;
  }
  if (projectFolderPath) {
    payload.folder = projectFolderPath;
  }

  payload.proactive_push_use_global = proactivePushUseGlobal;
  if (!proactivePushUseGlobal) {
    payload.proactive_push_enabled = proactivePushEnabled;
    payload.proactive_push_branch = proactivePushBranch;
  }

  if (!Object.keys(payload).length) {
    showMessage("没有可保存的项目设置", true);
    return;
  }

  await api(`/api/projects/${encodeURIComponent(state.projectId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

  await loadProject();
  await loadVersions();
  if (state.currentSession) {
    await loadSession(state.currentSession.id);
  }
  showMessage("项目设置已保存", false);
}

async function openFolder() {
  await api(`/api/projects/${encodeURIComponent(state.projectId)}/folder/open`, {
    method: "POST",
  });
  showMessage("已触发系统文件管理器", false);
}

async function onPickProjectFolderPath() {
  const input = document.getElementById("project-folder-path");
  const selected = await pickFolder(input.value.trim());
  if (selected) {
    input.value = selected;
  }
}

async function onPickProjectDocFolder() {
  const input = document.getElementById("project-doc-path");
  const current = input.value.trim();
  const initialDir = current.toLowerCase().endsWith(".md")
    ? current.replace(/[\\/][^\\/]*$/, "")
    : current;
  const selected = await pickFolder(initialDir);
  if (selected) {
    input.value = toProjectDocPath(selected);
  }
}

function toProjectDocPath(folder) {
  if (!folder) {
    return "";
  }
  const normalized = folder.endsWith("\\") || folder.endsWith("/") ? folder.slice(0, -1) : folder;
  const sep = normalized.includes("\\") ? "\\" : "/";
  return `${normalized}${sep}PROJECT.md`;
}

function renderDocPreview(markdown) {
  const preview = document.getElementById("doc-preview");
  if (!markdown) {
    preview.innerHTML = "<p>暂无文档内容。</p>";
    return;
  }

  if (window.marked && typeof window.marked.parse === "function") {
    preview.innerHTML = window.marked.parse(markdown);
  } else {
    preview.textContent = markdown;
  }
}

function renderDiffPreview(diffText) {
  const preview = document.getElementById("diff-preview");
  if (!diffText) {
    preview.textContent = "";
    preview.style.display = "none";
    return;
  }
  preview.style.display = "block";
  preview.textContent = diffText;
}

function initializeStatusUi() {
  Object.keys(PRIMARY_ACTION_BUSY_LABELS).forEach((id) => {
    const button = document.getElementById(id);
    if (button && !button.dataset.defaultText) {
      button.dataset.defaultText = button.textContent || "";
    }
  });
  hideGlobalStatusIfIdle(true);
}

async function runWithGlobalStatus(config, action) {
  if (state.ui.busy) {
    showMessage("AI 正在处理中，请稍候。", false);
    return false;
  }

  const startText = config?.startText || "AI思考中...";
  const successText = config?.successText || "处理完成";
  const errorTextPrefix = config?.errorTextPrefix || "处理失败：";
  const autoCap = Number.isFinite(config?.autoCap) ? Number(config.autoCap) : 88;

  state.ui.busy = true;
  setPrimaryActionsBusy(true);
  showGlobalStatus({ text: startText, progress: 4, mode: "busy" });
  startAutoProgress(autoCap);

  const updateProgress = (progress, text) => {
    if (typeof progress === "number") {
      setGlobalStatusProgress(progress);
    }
    if (text) {
      showGlobalStatus({ text, progress: state.ui.progress, mode: "busy" });
    }
  };

  try {
    await action(updateProgress);
    stopAutoProgress();
    showGlobalStatus({ text: successText, progress: 100, mode: "done" });
    window.setTimeout(() => hideGlobalStatusIfIdle(false), 900);
    return true;
  } catch (error) {
    stopAutoProgress();
    const message = `${errorTextPrefix}${buildErrorMessage(error)}`;
    showGlobalStatus({ text: message, progress: 100, mode: "error" });
    window.setTimeout(() => hideGlobalStatusIfIdle(false), 2600);
    throw error;
  } finally {
    state.ui.busy = false;
    setPrimaryActionsBusy(false);
  }
}

function setPrimaryActionsBusy(isBusy) {
  Object.entries(PRIMARY_ACTION_BUSY_LABELS).forEach(([id, busyText]) => {
    const button = document.getElementById(id);
    if (!button) {
      return;
    }

    if (!button.dataset.defaultText) {
      button.dataset.defaultText = button.textContent || "";
    }

    if (isBusy) {
      button.dataset.prevDisabled = button.disabled ? "1" : "0";
      button.disabled = true;
      button.textContent = busyText;
      return;
    }

    button.disabled = button.dataset.prevDisabled === "1";
    button.textContent = button.dataset.defaultText || button.textContent;
    delete button.dataset.prevDisabled;
  });
}

function startAutoProgress(cap) {
  stopAutoProgress();
  const normalizedCap = Math.max(15, Math.min(96, Number(cap) || 88));
  state.ui.autoProgressCap = normalizedCap;

  state.ui.timer = window.setInterval(() => {
    if (!state.ui.busy || state.ui.progress >= state.ui.autoProgressCap) {
      return;
    }

    const remain = state.ui.autoProgressCap - state.ui.progress;
    const step = remain > 28 ? 3 : remain > 12 ? 2 : 1;
    setGlobalStatusProgress(state.ui.progress + step);
  }, 260);
}

function stopAutoProgress() {
  if (state.ui.timer) {
    window.clearInterval(state.ui.timer);
    state.ui.timer = null;
  }
}

function setGlobalStatusProgress(value) {
  const normalized = Math.max(0, Math.min(100, Math.round(value)));
  state.ui.progress = normalized;

  const progressBar = document.getElementById("global-status-progress");
  const percent = document.getElementById("global-status-percent");
  if (progressBar) {
    progressBar.style.width = `${normalized}%`;
  }
  if (percent) {
    percent.textContent = `${normalized}%`;
  }
}

function showGlobalStatus({ text, progress, mode }) {
  const statusBar = document.getElementById("global-status");
  const statusText = document.getElementById("global-status-text");
  if (!statusBar || !statusText) {
    return;
  }

  statusBar.hidden = false;
  statusBar.classList.remove("busy", "done", "error");
  statusBar.classList.add(mode || "busy");
  statusText.textContent = text || "处理中...";

  if (typeof progress === "number") {
    setGlobalStatusProgress(progress);
  }
}

function hideGlobalStatusIfIdle(force) {
  if (!force && state.ui.busy) {
    return;
  }

  const statusBar = document.getElementById("global-status");
  if (!statusBar) {
    return;
  }

  statusBar.hidden = true;
  statusBar.classList.remove("busy", "done", "error");
  setGlobalStatusProgress(0);
}

function showMessage(message, isError) {
  const el = document.getElementById("project-message");
  el.textContent = message;
  el.classList.remove("error", "ok");
  el.classList.add(isError ? "error" : "ok");
  if (isError) {
    console.error(`[DocAgent][Project] ${message}`);
    window.alert(message);
  }
}

async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
    });
  } catch (error) {
    throw new Error(`网络请求失败：${buildErrorMessage(error)}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    if (contentType.includes("application/json")) {
      const payload = await response.json().catch(() => ({}));
      const detail = extractApiErrorMessage(payload);
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function pickFolder(initialDir) {
  const result = await api("/api/system/pick-folder", {
    method: "POST",
    body: JSON.stringify({ initial_dir: initialDir || null }),
  });
  return result?.selected ? result.path : "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function withErrorHandling(context, action) {
  return async () => {
    try {
      await action();
    } catch (error) {
      reportError(context, error);
    }
  };
}

function setupGlobalErrorHandlers() {
  window.addEventListener("error", (event) => {
    const err = event.error;
    if (err && err.__docagentHandled) {
      return;
    }
    const message = buildErrorMessage(err || event.message || "未知错误");
    showMessage(`发生未处理错误：${message}`, true);
    console.error("[DocAgent][Project][UnhandledError]", err || event);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    if (reason && reason.__docagentHandled) {
      return;
    }
    const message = buildErrorMessage(reason);
    showMessage(`发生未处理 Promise 错误：${message}`, true);
    console.error("[DocAgent][Project][UnhandledRejection]", reason);
  });
}

function reportError(context, error) {
  markHandled(error);
  const message = `${context}失败：${buildErrorMessage(error)}`;
  console.error(`[DocAgent][Project][${context}]`, error);
  showMessage(message, true);
}

function buildErrorMessage(error) {
  if (!error) {
    return "未知错误";
  }
  if (typeof error === "string") {
    return error;
  }
  if (error instanceof Error) {
    return error.message || "未知错误";
  }
  return String(error);
}

function markHandled(error) {
  if (error && typeof error === "object") {
    error.__docagentHandled = true;
  }
}

function extractApiErrorMessage(payload) {
  if (!payload) {
    return "";
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload.errors) && payload.errors.length) {
    return payload.errors.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  if (typeof payload.message === "string") {
    return payload.message;
  }
  return "";
}
