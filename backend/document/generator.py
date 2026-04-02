from __future__ import annotations

import logging
import re
from typing import Any


DEFAULT_PROJECT_DOC_PATTERN = "docs/project/PROJECT.md"
DEFAULT_PROACTIVE_PUSH_INSTRUCTION = "请你积极上传，每当开发完一个功能，则进行一次上传"
AUTO_BLOCK_START = "<!-- DOCAGENT_AUTO_INSTRUCTIONS_START -->"
AUTO_BLOCK_END = "<!-- DOCAGENT_AUTO_INSTRUCTIONS_END -->"


def generate_initial_document(
    project_name: str,
    *,
    proactive_push_enabled: bool = False,
    proactive_push_branch: str = "",
    root_agent_doc_path: str = "AGENT_DEVELOPMENT.md",
) -> str:
    proactive_lines = _build_proactive_push_lines(proactive_push_enabled, proactive_push_branch)

    return f"""# 项目功能清单

- 等待用户输入原始需求后生成。

# 项目细节

## 用户交互细节
- 等待需求澄清。

## 业务流程细节
- 等待需求澄清。

## 非功能需求细节
- 等待需求澄清。

## 依赖与环境
- Python 3.9+

## 项目开发文档管理规范
- 项目开发文档路径遵循全局配置 `doc_paths.project_doc`（默认 `docs/project/PROJECT.md`）。
- 开发项目的 Agent 负责维护项目开发文档，DocAgent 仅读取该文档作为上下文。
- 项目开发文档建议记录实现清单、部署说明、配置项说明、测试结果与待办事项。

## Agent开发文档输出规范
- 当前会话最新 Agent 开发文档固定输出到项目根目录：`{root_agent_doc_path}`。
- 同时保留版本历史，便于回溯和恢复。

## 积极上传规范
{proactive_lines}

# 代码架构与实现方式

## 技术栈选型
- 等待需求澄清。

## 目录结构
- 等待需求澄清。

## 核心模块设计
- 等待需求澄清。

## 数据模型
- 等待需求澄清。

## 接口定义
- 等待需求澄清。

---

> 当前项目：{project_name}
"""


def apply_contextual_instructions(
    content: str,
    *,
    project_name: str,
    history: list[dict[str, Any]],
    config: dict[str, Any] | None,
    project_doc_path: str = "",
    proactive_push_enabled: bool = False,
    proactive_push_branch: str = "",
) -> str:
    intent_text = _collect_user_intent_text(history)
    should_add_update = _should_add_update_project_doc_instruction(intent_text)
    should_add_proactive = _should_add_proactive_push_instruction(intent_text)

    instructions: list[str] = []

    if should_add_update:
        resolved_project_doc = resolve_project_doc_path(
            project_name=project_name,
            config=config,
        )
        instructions.append(
            "- 要求Agent更新项目开发文档，其路径为："
            f"`{resolved_project_doc}`。"
            "更新后的文档应至少包含“项目概述”、“项目详细介绍”、“项目架构”、“已实现的功能清单”等关键部分，"
            "并依据开发实际情况进行更新维护。"
        )

    if should_add_proactive and proactive_push_enabled:
        push_instruction = resolve_proactive_push_instruction(config=config)
        instructions.append(f"- {push_instruction}")

    return _merge_auto_instruction_block(content, instructions)


def resolve_project_doc_path(
    *,
    project_name: str,
    config: dict[str, Any] | None,
    project_doc_path: str = "",
) -> str:
    logger = logging.getLogger("docagent.system")

    path_pattern = ""
    try:
        # AGENT_DEVELOPMENT.md 指令路径仅从全局配置 doc_paths.project_doc 读取。
        path_pattern = str((config or {}).get("doc_paths", {}).get("project_doc", "")).strip()
    except Exception as exc:
        logger.warning("resolve_project_doc_path_failed_to_read_config error=%s", exc)
        path_pattern = ""

    if not path_pattern:
        path_pattern = DEFAULT_PROJECT_DOC_PATTERN

    project_token = _normalize_project_name_for_path(project_name)
    try:
        return path_pattern.replace("PROJECT", project_token)
    except Exception as exc:
        logger.warning("resolve_project_doc_path_failed_to_format path_pattern=%s error=%s", path_pattern, exc)
        return DEFAULT_PROJECT_DOC_PATTERN.replace("PROJECT", project_token)


def resolve_proactive_push_branch(*, proactive_push_branch: str, config: dict[str, Any] | None) -> str:
    branch = str(proactive_push_branch or "").strip()
    if branch:
        return branch

    try:
        return str((config or {}).get("workflow", {}).get("proactive_push_branch_default", "")).strip()
    except Exception:
        return ""


def resolve_proactive_push_instruction(*, config: dict[str, Any] | None) -> str:
    try:
        instruction = str((config or {}).get("workflow", {}).get("proactive_push_instruction", "")).strip()
    except Exception:
        instruction = ""
    return instruction or DEFAULT_PROACTIVE_PUSH_INSTRUCTION


def generate_document_from_context(
    *,
    project_name: str,
    project_doc_path: str,
    project_doc_exists: bool,
    history: list[dict[str, Any]],
    unresolved_points: list[str],
    previous_document: str,
    proactive_push_enabled: bool = False,
    proactive_push_branch: str = "",
    root_agent_doc_path: str = "AGENT_DEVELOPMENT.md",
) -> str:
    answers = _collect_answer_lines(history)
    function_items = _derive_function_items(answers)
    proactive_lines = _build_proactive_push_lines(proactive_push_enabled, proactive_push_branch)

    unresolved_lines = "\n".join(f"- {item}" for item in unresolved_points) if unresolved_points else "- 已收敛"
    answer_lines = "\n".join(f"- {line}" for line in answers[-8:]) if answers else "- 暂无"
    project_doc_state = "已提供" if project_doc_exists else "尚未提供"

    document = f"""# 项目功能清单

{function_items}

# 项目细节

## 用户交互细节
- 采用多轮问答澄清需求，问题由系统动态生成。
- 每轮提供 3-5 个选项，并支持“其他/补充”自由输入。

## 业务流程细节
- 会话内维护问题、回答、待解决问题清单与当前文档。
- 每次提交答案后，系统更新文档并生成版本快照。
- 当前待解决问题：
{unresolved_lines}

## 非功能需求细节
- 需要容错处理：API失败或项目文档缺失时仍可继续。
- 要求响应可追踪：保存会话历史和文档版本。

## 依赖与环境
- Python 3.9+
- FastAPI + requests + 原生前端

## 项目开发文档管理规范
- 项目开发文档固定位置：`{project_doc_path}`。
- 当前项目开发文档状态：{project_doc_state}。
- 项目开发文档由开发项目的 Agent 维护，DocAgent 仅做读取。
- 开发项目的 Agent 更新功能后，应同步回写项目开发文档。

## Agent开发文档输出规范
- 最新 Agent 开发文档固定输出到项目根目录：`{root_agent_doc_path}`。
- 每次需求更新后都要覆盖该文件，并保存版本快照。

## 积极上传规范
{proactive_lines}

# 代码架构与实现方式

## 技术栈选型
- 后端：FastAPI
- 前端：HTML/CSS/JS + Fetch API + marked.js
- 存储：JSON + Markdown 文件

## 目录结构
- backend：业务逻辑与 API
- frontend：页面与交互
- tests：测试与回归验证

## 核心模块设计
- 项目管理模块：负责项目创建、打开、迁移与元数据维护。
- 会话管理模块：负责会话生命周期与持久化。
- 对话模块：负责提示词构建、LLM调用与结果解析。
- 文档模块：负责项目文档加载、开发文档生成与版本管理。

## 数据模型
- 项目：id/name/folder/时间戳/项目文档路径
- 会话：历史对话、当前问题、待解决问题、当前文档

## 接口定义
- 采用 REST 风格 API，覆盖配置、项目、会话、回答、文档版本。

---

## 最近澄清摘要

{answer_lines}
"""

    return ensure_required_sections(document, previous_document=previous_document)


def ensure_required_sections(content: str, previous_document: str = "") -> str:
    required_headers = ["# 项目功能清单", "# 项目细节", "# 代码架构与实现方式"]
    if all(header in content for header in required_headers):
        return content

    if previous_document and all(header in previous_document for header in required_headers):
        return previous_document

    return generate_initial_document("未命名项目")


def _collect_answer_lines(history: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for turn in history:
        question = str(turn.get("question", "")).strip()
        answer = str(turn.get("answer", "")).strip()
        if not question and not answer:
            continue
        lines.append(f"{question} -> {answer}")
    return lines


def _derive_function_items(answer_lines: list[str]) -> str:
    if not answer_lines:
        return "- 待澄清：目标用户、核心场景、输入输出。"

    items = [f"- 需求线索：{line}" for line in answer_lines[-5:]]
    return "\n".join(items)


def _build_proactive_push_lines(proactive_push_enabled: bool, proactive_push_branch: str) -> str:
    if not proactive_push_enabled:
        return "- 当前未启用“积极上传”要求。"

    branch = proactive_push_branch.strip()
    if branch:
        return (
            f"- 已启用“积极上传”：开发项目的 Agent 每完成一个新功能，必须立即提交并上传到 `{branch}` 分支。\n"
            "- 提交信息需明确对应功能点和影响范围。"
        )

    return (
        "- 已启用“积极上传”：开发项目的 Agent 每完成一个新功能，必须立即提交并上传远程仓库。\n"
        "- 未指定分支时，不强制强调分支名称。"
    )


def _collect_user_intent_text(history: list[dict[str, Any]]) -> str:
    pieces: list[str] = []
    for turn in history:
        answer = str(turn.get("answer", "")).strip()
        if answer:
            pieces.append(answer)

        text_input = str(turn.get("text_input", "")).strip()
        if text_input:
            pieces.append(text_input)

        selected_options = turn.get("selected_options", [])
        if isinstance(selected_options, list):
            for option in selected_options:
                normalized = str(option).strip()
                if normalized:
                    pieces.append(normalized)

    return "\n".join(pieces)


def _should_add_update_project_doc_instruction(text: str) -> bool:
    if not text.strip():
        return False

    if re.search(r"(不要|不需要|无需|不用|不必).{0,10}(更新|维护).{0,10}项目开发文档", text):
        return False

    patterns = [
        r"(更新|维护|回写|同步).{0,10}项目开发文档",
        r"项目开发文档.{0,10}(更新|维护|回写|同步)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _should_add_proactive_push_instruction(text: str) -> bool:
    if not text.strip():
        return False

    if re.search(r"(不要|不需要|无需|不用|不必|关闭|取消).{0,10}(积极上传|自动推送|上传)", text):
        return False

    patterns = [
        r"积极上传",
        r"(自动|主动).{0,6}(推送|上传)",
        r"完成一个功能后.{0,8}(推送|上传)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _normalize_project_name_for_path(project_name: str) -> str:
    normalized = str(project_name or "").strip() or "PROJECT"
    normalized = re.sub(r"[\\/:*?\"<>|]", "-", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    return normalized


def _merge_auto_instruction_block(content: str, instructions: list[str]) -> str:
    cleaned_content, had_block = _remove_auto_instruction_block(content)

    if not instructions:
        return cleaned_content if had_block else content

    block = "\n".join(
        [
            AUTO_BLOCK_START,
            "## Agent执行附加指令",
            *instructions,
            AUTO_BLOCK_END,
        ]
    )

    base = cleaned_content.rstrip()
    if not base:
        return block + "\n"
    return base + "\n\n" + block + "\n"


def _remove_auto_instruction_block(content: str) -> tuple[str, bool]:
    pattern = re.compile(
        re.escape(AUTO_BLOCK_START) + r".*?" + re.escape(AUTO_BLOCK_END),
        re.DOTALL,
    )
    cleaned, count = pattern.subn("", content)
    return cleaned.strip() + ("\n" if cleaned.strip() else ""), count > 0
