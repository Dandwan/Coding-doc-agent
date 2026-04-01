from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.agent.question_parser import parse_questions_and_options, parse_tag_values
from backend.api.llm_client import LLMClient
from backend.config_manager import ConfigManager
from backend.document.generator import ensure_required_sections, generate_document_from_context
from backend.document.loader import load_project_document
from backend.utils.file_utils import now_iso


class ConversationService:
    def __init__(self, config_manager: ConfigManager) -> None:
        self.config_manager = config_manager

    def process_answer(self, project: dict[str, Any], session: dict[str, Any], answer_payload: dict[str, Any]) -> dict[str, Any]:
        current_question = str(session.get("current_question", {}).get("question", "请描述你的需求"))
        answer_text = self._format_answer(answer_payload)

        history = list(session.get("history", []))
        history.append(
            {
                "timestamp": now_iso(),
                "question": current_question,
                "answer": answer_text,
                "selected_options": list(answer_payload.get("selected_options", [])),
                "text_input": str(answer_payload.get("text_input", "")),
                "skip_question": bool(answer_payload.get("skip_question", False)),
            }
        )
        session["history"] = history

        pending_questions = list(session.get("pending_questions", []))
        if pending_questions:
            pending_questions.pop(0)

        if bool(session.get("is_complete", False)) and not answer_payload.get("skip_question"):
            session["is_complete"] = False
            session["user_confirmed_complete"] = False

        user_input = self._normalize_user_input(answer_payload)

        config = self.config_manager.load()
        prompt_settings = self._get_prompt_settings(config)
        project_doc_path = project.get("project_doc_path") or config["doc_paths"]["project_doc"]
        project_doc_content = load_project_document(project["folder"], project_doc_path) or ""

        proactive_push_enabled = bool(project.get("proactive_push_enabled", False))
        proactive_push_branch = str(project.get("proactive_push_branch", "")).strip()
        root_agent_doc_path = str(project.get("root_agent_doc_path", "AGENT_DEVELOPMENT.md"))

        if pending_questions:
            session["pending_questions"] = pending_questions
            session["current_question"] = pending_questions[0]
            session["unresolved_points"] = [item.get("question", "") for item in pending_questions if item.get("question")]
            session["ai_thinks_clear"] = False
            if user_input:
                session["last_user_input"] = user_input
            session.pop("last_error", None)
            return session

        ai_result = self._run_ai_round(
            config=config,
            prompt_settings=prompt_settings,
            project_doc_content=project_doc_content,
            user_input=user_input,
            history=history,
        )

        error_text = ai_result.get("error", "")
        questions = ai_result.get("questions", [])

        if questions:
            session["pending_questions"] = questions
            session["current_question"] = questions[0]
            session["unresolved_points"] = [item.get("question", "") for item in questions if item.get("question")]
            session["ai_thinks_clear"] = False
            session["is_complete"] = False
        else:
            previous_document = str(session.get("current_document", ""))
            current_document = str(ai_result.get("document_markdown", "")).strip()
            if not current_document:
                current_document = generate_document_from_context(
                    project_name=project.get("name", "未命名项目"),
                    project_doc_path=project_doc_path,
                    project_doc_exists=bool(project_doc_content.strip()),
                    history=history,
                    unresolved_points=[],
                    previous_document=previous_document,
                    proactive_push_enabled=proactive_push_enabled,
                    proactive_push_branch=proactive_push_branch,
                    root_agent_doc_path=Path(root_agent_doc_path).name,
                )
            current_document = ensure_required_sections(current_document, previous_document=previous_document)

            session["pending_questions"] = []
            session["current_question"] = {
                "question": "AI 认为当前需求细节已清晰。你可以继续补充新需求，或点击“完成并保存对话”。",
                "options": [],
            }
            session["unresolved_points"] = []
            session["current_document"] = current_document
            session["ai_thinks_clear"] = True
            session["is_complete"] = False

        if user_input:
            session["last_user_input"] = user_input

        if error_text:
            session["last_error"] = error_text
        else:
            session.pop("last_error", None)

        return session

    def finish_session(self, session: dict[str, Any]) -> dict[str, Any]:
        session["is_complete"] = True
        session["ai_thinks_clear"] = bool(session.get("ai_thinks_clear", False))
        session["user_confirmed_complete"] = True
        session["current_question"] = {
            "question": "已完成并保存当前会话。你仍可继续补充新需求，系统将重新进入澄清循环。",
            "options": [],
        }
        session["pending_questions"] = []
        session["unresolved_points"] = []
        return session

    def _run_ai_round(
        self,
        *,
        config: dict[str, Any],
        prompt_settings: dict[str, Any],
        project_doc_content: str,
        user_input: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        placeholders = prompt_settings.get("placeholders", {})
        markers = prompt_settings.get("markers", {})

        question_open = str(markers.get("question_open", "<question>"))
        question_close = str(markers.get("question_close", "</question>"))
        option_open = str(markers.get("option_open", "<option>"))
        option_close = str(markers.get("option_close", "</option>"))

        qa_text = self._build_question_and_input_text(history)

        try:
            clarify_prompt = self._render_template(
                str(prompt_settings.get("clarify_prompt_template", "")),
                placeholders=placeholders,
                project_document=project_doc_content,
                user_input=user_input,
                question_and_input=qa_text,
            )
            clarify_raw = self._query_llm(api_config=config.get("api", {}), prompt=clarify_prompt)

            parsed_questions = parse_questions_and_options(
                clarify_raw,
                question_open=question_open,
                question_close=question_close,
                option_open=option_open,
                option_close=option_close,
            )

            questions: list[dict[str, Any]] = []
            for question_item in parsed_questions:
                question = str(question_item.get("question", "")).strip()
                if not question:
                    continue

                options_prompt = self._render_template(
                    str(prompt_settings.get("options_prompt_template", "")),
                    placeholders=placeholders,
                    project_document=project_doc_content,
                    user_input=user_input,
                    question_and_input=f"{qa_text}\n\n[当前问题]\n{question}",
                )
                options_prompt += (
                    f"\n\n请仅用标记输出该问题选项："
                    f"{option_open}选项文本{option_close}。"
                )
                options_raw = self._query_llm(api_config=config.get("api", {}), prompt=options_prompt)
                options = parse_tag_values(options_raw, option_open, option_close)
                if not options:
                    options = [str(item).strip() for item in question_item.get("options", []) if str(item).strip()]

                questions.append({"question": question, "options": options[:6]})

            if questions:
                return {"questions": questions, "document_markdown": "", "error": ""}

            final_prompt = self._render_template(
                str(prompt_settings.get("final_doc_prompt_template", "")),
                placeholders=placeholders,
                project_document=project_doc_content,
                user_input=user_input,
                question_and_input=qa_text,
            )
            final_prompt += (
                "\n\n请输出 Markdown 文档，并确保至少包含以下一级标题："
                "\n# 项目功能清单\n# 项目细节\n# 代码架构与实现方式"
                "\n同时在文档中必须明确：将要开发的新功能、开发步骤、细节要求。"
            )
            final_raw = self._query_llm(api_config=config.get("api", {}), prompt=final_prompt)
            final_doc = self._strip_code_fence(final_raw)
            return {"questions": [], "document_markdown": final_doc, "error": ""}
        except Exception as exc:
            return {"questions": [], "document_markdown": "", "error": str(exc)}

    def _query_llm(self, *, api_config: dict[str, Any], prompt: str) -> str:
        client = LLMClient(
            url=str(api_config.get("url", "")),
            api_key=str(api_config.get("api_key", "")),
            model=str(api_config.get("model", "")),
            temperature=float(api_config.get("temperature", 0.7)),
            timeout=int(api_config.get("timeout", 60)),
            max_retries=int(api_config.get("max_retries", 2)),
        )
        messages = [{"role": "user", "content": prompt}]
        return client.get_response(messages)

    def _render_template(
        self,
        template: str,
        *,
        placeholders: dict[str, Any],
        project_document: str,
        user_input: str,
        question_and_input: str,
    ) -> str:
        rendered = template or ""

        project_token = str(placeholders.get("project_document", "</projectDocument>"))
        user_token = str(placeholders.get("user_input", "</userInput>"))
        qa_token = str(placeholders.get("question_and_input", "</questionAndInput>"))

        rendered = rendered.replace(project_token, project_document or "(项目开发文档为空)")
        rendered = rendered.replace(user_token, user_input or "(本轮用户输入为空)")
        rendered = rendered.replace(qa_token, question_and_input or "(暂无历史问答)")
        return rendered

    def _build_question_and_input_text(self, history: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for index, turn in enumerate(history, start=1):
            question = str(turn.get("question", "")).strip() or "(无问题文本)"
            answer = str(turn.get("answer", "")).strip() or "(无回答文本)"
            lines.append(f"[{index}] 问题: {question}")
            lines.append(f"[{index}] 回答: {answer}")
        return "\n".join(lines)

    def _normalize_user_input(self, answer_payload: dict[str, Any]) -> str:
        if answer_payload.get("skip_question"):
            return "用户选择跳过该问题"

        options = [str(item).strip() for item in answer_payload.get("selected_options", []) if str(item).strip()]
        text_input = str(answer_payload.get("text_input", "")).strip()

        if options:
            if text_input:
                return f"已选选项: {' / '.join(options)}; 用户补充: {text_input}"
            return f"已选选项: {' / '.join(options)}"

        return text_input

    def _format_answer(self, answer_payload: dict[str, Any]) -> str:
        normalized = self._normalize_user_input(answer_payload)
        return normalized if normalized else "无有效回答"

    def _get_prompt_settings(self, config: dict[str, Any]) -> dict[str, Any]:
        prompt_settings = config.get("prompt_settings", {})
        placeholders = prompt_settings.get("placeholders", {})
        markers = prompt_settings.get("markers", {})

        prompt_settings.setdefault("clarify_prompt_template", "")
        prompt_settings.setdefault("options_prompt_template", "")
        prompt_settings.setdefault("final_doc_prompt_template", "")
        prompt_settings["placeholders"] = {
            "project_document": str(placeholders.get("project_document", "</projectDocument>")),
            "user_input": str(placeholders.get("user_input", "</userInput>")),
            "question_and_input": str(placeholders.get("question_and_input", "</questionAndInput>")),
        }
        prompt_settings["markers"] = {
            "question_open": str(markers.get("question_open", "<question>")),
            "question_close": str(markers.get("question_close", "</question>")),
            "option_open": str(markers.get("option_open", "<option>")),
            "option_close": str(markers.get("option_close", "</option>")),
        }
        return prompt_settings

    def _strip_code_fence(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)
        return cleaned.strip()
