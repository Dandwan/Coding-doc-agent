const state = {
  config: null,
  projects: [],
};

document.addEventListener("DOMContentLoaded", () => {
  const useDefault = document.getElementById("use-default-folder");
  const folderInput = document.getElementById("project-folder");
  const pickFolderBtn = document.getElementById("pick-project-folder");

  document.getElementById("open-settings").addEventListener("click", () => {
    window.location.href = "/settings";
  });

  pickFolderBtn.addEventListener("click", async () => {
    try {
      const selected = await pickFolder(folderInput.value.trim());
      if (selected) {
        folderInput.value = selected;
      }
    } catch (error) {
      showCreateMessage(`选择文件夹失败：${error.message}`, true);
    }
  });

  useDefault.addEventListener("change", () => {
    folderInput.disabled = useDefault.checked;
    pickFolderBtn.disabled = useDefault.checked;
    if (useDefault.checked) {
      folderInput.value = "";
    }
  });

  document.getElementById("create-project-form").addEventListener("submit", onCreateProject);

  folderInput.disabled = useDefault.checked;
  pickFolderBtn.disabled = useDefault.checked;
  bootstrap().catch((error) => {
    showCreateMessage(`初始化失败：${error.message}`, true);
  });
});

async function bootstrap() {
  await loadConfig();
  await loadProjects();
}

async function loadConfig() {
  state.config = await api("/api/config");
}

async function loadProjects() {
  state.projects = await api("/api/projects");
  renderProjects();
}

function renderProjects() {
  const list = document.getElementById("projects-list");
  list.innerHTML = "";

  if (!state.projects.length) {
    list.innerHTML = '<div class="project-item"><p>暂无项目，先创建一个开始。</p></div>';
    return;
  }

  for (const project of state.projects) {
    const card = document.createElement("div");
    card.className = "project-item";
    card.innerHTML = `
      <h4>${escapeHtml(project.name)}</h4>
      <p>路径：${escapeHtml(project.folder)}</p>
      <p>更新时间：${escapeHtml(project.updated_at || "-")}</p>
      <div class="actions">
        <button data-action="open">打开项目</button>
        <button data-action="delete" class="danger">移除索引</button>
      </div>
    `;

    card.querySelector('[data-action="open"]').addEventListener("click", () => {
      window.location.href = `/project?project_id=${encodeURIComponent(project.id)}`;
    });

    card.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      const confirmed = window.confirm("确认将项目从列表中移除？不会删除项目文件夹。");
      if (!confirmed) {
        return;
      }
      await api(`/api/projects/${encodeURIComponent(project.id)}`, {
        method: "DELETE",
      });
      await loadProjects();
    });

    list.appendChild(card);
  }
}

async function onCreateProject(event) {
  event.preventDefault();
  const nameInput = document.getElementById("project-name");
  const folderInput = document.getElementById("project-folder");
  const useDefault = document.getElementById("use-default-folder");

  const name = nameInput.value.trim();
  const folder = useDefault.checked ? "" : folderInput.value.trim();

  if (!name) {
    showCreateMessage("项目名称不能为空", true);
    return;
  }

  const payload = { name };
  if (folder) {
    payload.folder = folder;
  }

  try {
    const created = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    showCreateMessage(`项目创建成功：${created.name}`, false);
    nameInput.value = "";
    if (!useDefault.checked) {
      folderInput.value = "";
    }
    await loadProjects();
  } catch (error) {
    showCreateMessage(`创建失败：${error.message}`, true);
  }
}

function showCreateMessage(message, isError) {
  const el = document.getElementById("create-message");
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
