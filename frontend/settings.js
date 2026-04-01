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

  document.getElementById("pick-project-doc-path").addEventListener("click", async () => {
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
  document.getElementById("global-proactive-push-enabled").checked =
    config.workflow?.proactive_push_enabled_default || false;
  document.getElementById("global-proactive-push-branch").value =
    config.workflow?.proactive_push_branch_default || "";

  document.getElementById("clarify-prompt-template").value =
    config.prompt_settings?.clarify_prompt_template || "";
  document.getElementById("options-prompt-template").value =
    config.prompt_settings?.options_prompt_template || "";
  document.getElementById("final-doc-prompt-template").value =
    config.prompt_settings?.final_doc_prompt_template || "";

  document.getElementById("ph-project-document").value =
    config.prompt_settings?.placeholders?.project_document || "</projectDocument>";
  document.getElementById("ph-user-input").value =
    config.prompt_settings?.placeholders?.user_input || "</userInput>";
  document.getElementById("ph-question-and-input").value =
    config.prompt_settings?.placeholders?.question_and_input || "</questionAndInput>";

  document.getElementById("marker-question-open").value =
    config.prompt_settings?.markers?.question_open || "<question>";
  document.getElementById("marker-question-close").value =
    config.prompt_settings?.markers?.question_close || "</question>";
  document.getElementById("marker-option-open").value =
    config.prompt_settings?.markers?.option_open || "<option>";
  document.getElementById("marker-option-close").value =
    config.prompt_settings?.markers?.option_close || "</option>";
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
    workflow: {
      proactive_push_enabled_default: document.getElementById("global-proactive-push-enabled").checked,
      proactive_push_branch_default: document.getElementById("global-proactive-push-branch").value.trim(),
    },
    prompt_settings: {
      clarify_prompt_template: document.getElementById("clarify-prompt-template").value,
      options_prompt_template: document.getElementById("options-prompt-template").value,
      final_doc_prompt_template: document.getElementById("final-doc-prompt-template").value,
      placeholders: {
        project_document: document.getElementById("ph-project-document").value.trim(),
        user_input: document.getElementById("ph-user-input").value.trim(),
        question_and_input: document.getElementById("ph-question-and-input").value.trim(),
      },
      markers: {
        question_open: document.getElementById("marker-question-open").value.trim(),
        question_close: document.getElementById("marker-question-close").value.trim(),
        option_open: document.getElementById("marker-option-open").value.trim(),
        option_close: document.getElementById("marker-option-close").value.trim(),
      },
    },
  };

  if (!payload.projects_root) {
    showMessage("默认项目根目录不能为空", true);
    return;
  }

  if (!payload.prompt_settings.clarify_prompt_template.trim()) {
    showMessage("请填写“识别需求不清晰点提示词”", true);
    return;
  }
  if (!payload.prompt_settings.options_prompt_template.trim()) {
    showMessage("请填写“生成选项提示词”", true);
    return;
  }
  if (!payload.prompt_settings.final_doc_prompt_template.trim()) {
    showMessage("请填写“生成最终文档提示词”", true);
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

function toProjectDocPath(folder) {
  if (!folder) {
    return "";
  }
  const normalized = folder.endsWith("\\") || folder.endsWith("/") ? folder.slice(0, -1) : folder;
  const sep = normalized.includes("\\") ? "\\" : "/";
  return `${normalized}${sep}PROJECT.md`;
}
