document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("go-home").addEventListener("click", () => {
    window.location.href = "/";
  });

  document.getElementById("pick-projects-root").addEventListener("click", async () => {
    try {
      const current = document.getElementById("projects-root").value.trim();
      const selected = await pickFolder(current);
      if (selected) {
        document.getElementById("projects-root").value = selected;
      }
    } catch (error) {
      showMessage(`选择文件夹失败：${error.message}`, true);
    }
  });

  document.getElementById("pick-agent-doc-dir").addEventListener("click", async () => {
    try {
      const current = document.getElementById("agent-doc-dir").value.trim();
      const selected = await pickFolder(current);
      if (selected) {
        document.getElementById("agent-doc-dir").value = selected;
      }
    } catch (error) {
      showMessage(`选择文件夹失败：${error.message}`, true);
    }
  });

  document.getElementById("save-config").addEventListener("click", onSaveConfig);

  loadConfig().catch((error) => {
    showMessage(`加载配置失败：${error.message}`, true);
  });
});

async function loadConfig() {
  const config = await api("/api/config");

  document.getElementById("projects-root").value = config.projects_root || "";
  document.getElementById("api-url").value = config.api?.url || "";
  document.getElementById("api-key").value = config.api?.api_key || "";
  document.getElementById("api-model").value = config.api?.model || "";
  document.getElementById("api-temperature").value = config.api?.temperature ?? 0.7;
  document.getElementById("api-timeout").value = config.api?.timeout ?? 60;
  document.getElementById("api-retries").value = config.api?.max_retries ?? 2;
  document.getElementById("project-doc-path").value = config.doc_paths?.project_doc || "docs/project/PROJECT.md";
  document.getElementById("agent-doc-dir").value = config.doc_paths?.agent_doc_dir || "docs/agent";
}

async function onSaveConfig() {
  const payload = {
    projects_root: document.getElementById("projects-root").value.trim(),
    api: {
      url: document.getElementById("api-url").value.trim(),
      api_key: document.getElementById("api-key").value.trim(),
      model: document.getElementById("api-model").value.trim(),
      temperature: Number(document.getElementById("api-temperature").value),
      timeout: Number(document.getElementById("api-timeout").value),
      max_retries: Number(document.getElementById("api-retries").value),
    },
    doc_paths: {
      project_doc: document.getElementById("project-doc-path").value.trim(),
      agent_doc_dir: document.getElementById("agent-doc-dir").value.trim(),
    },
  };

  if (!payload.projects_root) {
    showMessage("默认项目根目录不能为空", true);
    return;
  }

  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showMessage("配置保存成功", false);
  } catch (error) {
    showMessage(`保存失败：${error.message}`, true);
  }
}

function showMessage(message, isError) {
  const el = document.getElementById("settings-message");
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
