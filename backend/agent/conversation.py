from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent.prompt_builder import build_system_prompt
from backend.agent.question_parser import parse_llm_json
from backend.api.llm_client import LLMClient, LLMClientError
from backend.config_manager import ConfigManager
from backend.document.generator import ensure_required_sections, generate_document_from_context
from backend.document.loader import load_project_document
from backend.utils.file_utils import now_iso


class ConversationService:
    def __init__(self, config_manager: ConfigManager) -> None:
        self.config_manager = config_manager

    def process_answer(self, project: dict[str, Any], session: dict[str, Any], answer_payload: dict[str, Any]) -> dict[str, Any]:
        current_question = str(session.get("current_question", {}).get("question", "请补充需求"))
        answer_text = self._format_answer(answer_payload)
        was_complete = bool(session.get("is_complete", False))
        force_reverify = self._should_reverify(was_complete, answer_payload)

        history = list(session.get("history", []))
        history.append(
            {
                "timestamp": now_iso(),
                "question": current_question,
                "answer": answer_text,
            }
        )
        session["history"] = history

        if force_reverify:
            session["unresolved_points"] = self._ensure_reverify_points(session.get("unresolved_points", []))

        config = self.config_manager.load()
        project_doc_path = project.get("project_doc_path") or config["doc_paths"]["project_doc"]
        project_doc_content = load_project_document(project["folder"], project_doc_path)
        project_doc_exists = project_doc_content is not None
        proactive_push_enabled = bool(project.get("proactive_push_enabled", False))
        proactive_push_branch = str(project.get("proactive_push_branch", "")).strip()
        root_agent_doc_path = str(project.get("root_agent_doc_path", "AGENT_DEVELOPMENT.md"))

        parsed: dict[str, Any] | None = None
        llm_error = ""
        try:
            parsed = self._query_llm(
                config=config,
                project=project,
                session=session,
                answer_text=answer_text,
                project_doc_path=project_doc_path,
                project_doc_exists=project_doc_exists,
                project_doc_content=project_doc_content,
                proactive_push_enabled=proactive_push_enabled,
                proactive_push_branch=proactive_push_branch,
                force_reverify=force_reverify,
            )
        except Exception as exc:
            llm_error = str(exc)

        if parsed is None:
            parsed = self._fallback_result(session, force_reverify=force_reverify)

        seed_unresolved = session.get("unresolved_points", [])
        unresolved_points = parsed.get("unresolved_points", [])
        if not unresolved_points:
            unresolved_points = self._fallback_unresolved(seed_unresolved, answer_payload)

        if force_reverify:
            unresolved_points = self._ensure_reverify_points(unresolved_points)

        previous_document = str(session.get("current_document", ""))
        current_document = parsed.get("document_markdown") or generate_document_from_context(
            project_name=project.get("name", "未命名项目"),
            project_doc_path=project_doc_path,
            project_doc_exists=project_doc_exists,
            history=history,
            unresolved_points=unresolved_points,
            previous_document=previous_document,
            proactive_push_enabled=proactive_push_enabled,
            proactive_push_branch=proactive_push_branch,
            root_agent_doc_path=Path(root_agent_doc_path).name,
        )
        current_document = ensure_required_sections(current_document, previous_document=previous_document)

        is_complete = bool(parsed.get("is_complete", False))
        if force_reverify:
            is_complete = False
        elif len(history) >= 4 and len(unresolved_points) <= 1:
            is_complete = True

        session["current_question"] = {
            "question": parsed.get("next_question", "还有哪些细节需要补充？"),
            "options": parsed.get("options", ["继续细化功能", "完善接口定义", "补充测试与验收"]),
        }
        session["unresolved_points"] = unresolved_points
        session["current_document"] = current_document
        session["is_complete"] = is_complete
        if llm_error:
            session["last_error"] = llm_error
        else:
            session.pop("last_error", None)

        return session

    def _query_llm(
        self,
        *,
        config: dict[str, Any],
        project: dict[str, Any],
        session: dict[str, Any],
        answer_text: str,
        project_doc_path: str,
        project_doc_exists: bool,
        project_doc_content: str | None,
        proactive_push_enabled: bool,
        proactive_push_branch: str,
        force_reverify: bool,
    ) -> dict[str, Any]:
        api = config.get("api", {})
        client = LLMClient(
            url=str(api.get("url", "")),
            api_key=str(api.get("api_key", "")),
            model=str(api.get("model", "")),
            temperature=float(api.get("temperature", 0.7)),
            timeout=int(api.get("timeout", 60)),
            max_retries=int(api.get("max_retries", 2)),
        )

        system_prompt = build_system_prompt(
            project_name=project.get("name", "未命名项目"),
            project_doc_path=project_doc_path,
            project_doc_exists=project_doc_exists,
            project_doc_content=project_doc_content,
            proactive_push_enabled=proactive_push_enabled,
            proactive_push_branch=proactive_push_branch,
            force_reverify=force_reverify,
        )

        recent_history = session.get("history", [])[-8:]
        unresolved = session.get("unresolved_points", [])
        current_document = str(session.get("current_document", ""))
        if len(current_document) > 6000:
            current_document = current_document[:6000] + "\n\n[内容已截断]"

        user_prompt = {
            "recent_history": recent_history,
            "unresolved_points": unresolved,
            "latest_answer": answer_text,
            "current_document": current_document,
            "force_reverify": force_reverify,
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": str(user_prompt)},
        ]

        raw = client.get_response(messages)
        parsed = parse_llm_json(raw)
        return parsed

    def _fallback_result(self, session: dict[str, Any], *, force_reverify: bool = False) -> dict[str, Any]:
        if force_reverify:
            return {
                "next_question": "你新增的需求会影响哪些既有模块和接口？请逐项确认。",
                "options": ["功能边界影响", "数据结构影响", "API/交互影响", "测试与回归影响"],
                "unresolved_points": self._ensure_reverify_points(session.get("unresolved_points", [])),
                "document_markdown": "",
                "is_complete": False,
            }

        history_count = len(session.get("history", []))
        question_pool = [
            {
                "question": "该工具的输入数据来自哪里？",
                "options": ["手动输入", "文件上传", "第三方API", "数据库"],
            },
            {
                "question": "你希望输出结果以什么形式交付？",
                "options": ["网页展示", "Markdown 文档", "JSON/API", "文件导出"],
            },
            {
                "question": "部署与运行环境有哪些限制？",
                "options": ["本地运行", "服务器部署", "容器化", "跨平台兼容"],
            },
            {
                "question": "是否还有必须记录的风险、边界或验收条件？",
                "options": ["性能指标", "安全合规", "异常恢复", "测试覆盖"],
            },
        ]

        index = min(max(history_count - 1, 0), len(question_pool) - 1)
        selected = question_pool[index]

        return {
            "next_question": selected["question"],
            "options": selected["options"],
            "unresolved_points": session.get("unresolved_points", []),
            "document_markdown": "",
            "is_complete": False,
        }

    def _fallback_unresolved(self, unresolved_points: list[str], answer_payload: dict[str, Any]) -> list[str]:
        unresolved = list(unresolved_points)
        if not unresolved:
            unresolved = ["补充边界条件", "补充验收标准"]

        if answer_payload.get("skip_question"):
            if unresolved:
                unresolved.pop(0)
            return unresolved

        answered = bool(answer_payload.get("selected_options")) or bool(str(answer_payload.get("text_input", "")).strip())
        if answered and unresolved:
            unresolved.pop(0)

        return unresolved

    def _format_answer(self, answer_payload: dict[str, Any]) -> str:
        if answer_payload.get("skip_question"):
            return "用户选择跳过该问题"

        options = answer_payload.get("selected_options", [])
        text_input = str(answer_payload.get("text_input", "")).strip()

        parts: list[str] = []
        if options:
            parts.append("选项=" + " / ".join(str(item) for item in options))
        if text_input:
            parts.append("补充=" + text_input)

        return "；".join(parts) if parts else "无有效回答"

    def _should_reverify(self, was_complete: bool, answer_payload: dict[str, Any]) -> bool:
        if not was_complete:
            return False
        if answer_payload.get("skip_question"):
            return False

        has_options = bool(answer_payload.get("selected_options"))
        has_text = bool(str(answer_payload.get("text_input", "")).strip())
        return has_options or has_text

    def _ensure_reverify_points(self, unresolved_points: list[str]) -> list[str]:
        merged = [item for item in unresolved_points if str(item).strip()]
        required = [
            "新增需求影响范围确认",
            "新增需求验收标准确认",
            "新增需求回归测试与发布策略",
        ]
        for item in required:
            if item not in merged:
                merged.append(item)
        return merged
