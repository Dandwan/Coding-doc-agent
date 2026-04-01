const state = {
  projectId: "",
  project: null,
  sessions: [],
  currentSession: null,
  versions: [],
};

document.addEventListener("DOMContentLoaded", () => {
  state.projectId = new URLSearchParams(window.location.search).get("project_id") || "";

  bindStaticActions();

  if (!state.projectId) {
    showMessage("缺少 project_id，无法进入项目工作区", true);
    return;
  }

  bootstrap().catch((error) => {
    showMessage(`初始化失败：${error.message}`, true);
  });
});

function bindStaticActions() {
  document.getElementById("go-home").addEventListener("click", () => {
    window.location.href = "/";
  });
  document.getElementById("go-settings").addEventListener("click", () => {
    window.location.href = "/settings";
  });

  document.getElementById("open-folder-btn").addEventListener("click", openFolder);
  document
    .getElementById("proactive-push-use-global")
    .addEventListener("change", applyProactiveControlsState);
  document.getElementById("create-session").addEventListener("click", createSession);
  document.getElementById("rename-session").addEventListener("click", renameSession);
  document.getElementById("delete-session").addEventListener("click", deleteSession);
  document.getElementById("submit-answer").addEventListener("click", () => submitAnswer(false));
  document.getElementById("skip-question").addEventListener("click", () => submitAnswer(true));
  document.getElementById("save-project-settings").addEventListener("click", saveProjectSettings);
  document.getElementById("pick-project-folder-path").addEventListener("click", onPickProjectFolderPath);
  document.getElementById("pick-project-doc-folder").addEventListener("click", onPickProjectDocFolder);
  document.getElementById("view-version").addEventListener("click", viewVersion);
  document.getElementById("compare-version").addEventListener("click", compareVersion);
  document.getElementById("restore-version").addEventListener("click", restoreVersion);
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
    card.addEventListener("click", () => loadSession(session.id));
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
  showMessage("会话已创建", false);
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

  for (const item of state.currentSession.unresolved_points || []) {
    const li = document.createElement("li");
    li.textContent = item;
    unresolvedList.appendChild(li);
  }

  const history = state.currentSession.history || [];
  const recent = history.slice(-6).reverse();
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

  const response = await api(
    `/api/projects/${encodeURIComponent(state.projectId)}/sessions/${encodeURIComponent(state.currentSession.id)}/answer`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );

  state.currentSession = response.session;
  await loadProject();
  await loadVersions();
  renderSessions();
  renderSessionView();
  selectCurrentVersion();
  showMessage("回答已提交并生成新版本", false);
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
  try {
    const input = document.getElementById("project-folder-path");
    const selected = await pickFolder(input.value.trim());
    if (selected) {
      input.value = selected;
    }
  } catch (error) {
    showMessage(`选择文件夹失败：${error.message}`, true);
  }
}

async function onPickProjectDocFolder() {
  try {
    const input = document.getElementById("project-doc-path");
    const current = input.value.trim();
    const initialDir = current.toLowerCase().endsWith(".md")
      ? current.replace(/[\\/][^\\/]*$/, "")
      : current;
    const selected = await pickFolder(initialDir);
    if (selected) {
      input.value = toProjectDocPath(selected);
    }
  } catch (error) {
    showMessage(`选择文件夹失败：${error.message}`, true);
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

function showMessage(message, isError) {
  const el = document.getElementById("project-message");
  el.textContent = message;
  el.classList.remove("error", "ok");
  el.classList.add(isError ? "error" : "ok");
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
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
