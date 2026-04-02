from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from backend.agent.question_parser import parse_questions_and_options, parse_tag_values
from backend.api.llm_client import LLMClient
from backend.config_manager import ConfigManager
from backend.document.generator import (
    apply_contextual_instructions,
    ensure_required_sections,
    generate_document_from_context,
)
from backend.document.loader import load_project_document
from backend.logging_manager import get_logger
from backend.utils.file_utils import now_iso


class ConversationService:
    def __init__(self, config_manager: ConfigManager) -> None:
        self.config_manager = config_manager
        self.ai_logger = get_logger("ai")
        self.system_logger = get_logger("system")

    def process_answer(
        self,
        project: dict[str, Any],
        session: dict[str, Any],
        answer_payload: dict[str, Any],
    ) -> dict[str, Any]:
        project_id = str(project.get("id", "-"))
        session_id = str(session.get("id", "-"))
        current_question = str(session.get("current_question", {}).get("question", "请描述你的需求"))
        answer_text = self._format_answer(answer_payload)
        self.ai_logger.info(
            "dialog_user_input project_id=%s session_id=%s question=%s answer=%s",
            project_id,
            session_id,
            current_question,
            answer_text,
        )

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

        session_context_text = self._build_session_context_text(
            session_name=str(session.get("name", "当前会话")),
            history=history,
        )

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
            self.ai_logger.info(
                "dialog_pending_questions project_id=%s session_id=%s remain=%s",
                project_id,
                session_id,
                len(pending_questions),
            )
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
            session_context_text=session_context_text,
            project_id=project_id,
            session_id=session_id,
        )

        error_text = ai_result.get("error", "")
        questions = ai_result.get("questions", [])

        if error_text:
            session["pending_questions"] = []
            session["unresolved_points"] = []
            session["ai_thinks_clear"] = False
            session["is_complete"] = False
            session["current_question"] = {
                "question": "AI 调用失败，请检查日志与模型配置后重试本轮输入。",
                "options": [],
            }
            session["last_error"] = error_text
            self.system_logger.error(
                "dialog_ai_error project_id=%s session_id=%s error=%s",
                project_id,
                session_id,
                error_text,
            )
            if user_input:
                session["last_user_input"] = user_input
            return session

        if questions:
            if history:
                history[-1]["options"] = [
                    {
                        "question": str(item.get("question", "")).strip(),
                        "options": list(item.get("options", [])),
                    }
                    for item in questions
                ]
            session["pending_questions"] = questions
            session["current_question"] = questions[0]
            session["unresolved_points"] = [item.get("question", "") for item in questions if item.get("question")]
            session["ai_thinks_clear"] = False
            session["is_complete"] = False
            self.ai_logger.info(
                "dialog_questions_generated project_id=%s session_id=%s question_count=%s",
                project_id,
                session_id,
                len(questions),
            )
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
            current_document = apply_contextual_instructions(
                current_document,
                project_name=project.get("name", "未命名项目"),
                history=history,
                config=config,
                project_doc_path=project_doc_path,
                proactive_push_enabled=proactive_push_enabled,
                proactive_push_branch=proactive_push_branch,
            )

            session["pending_questions"] = []
            session["current_question"] = {
                "question": "AI 认为当前需求细节已清晰。你可以继续补充新需求，或点击“保存对话并生成Agent开发文档”。",
                "options": [],
            }
            session["unresolved_points"] = []
            session["current_document"] = current_document
            session["ai_thinks_clear"] = True
            session["is_complete"] = False
            self.ai_logger.info(
                "dialog_final_document_generated project_id=%s session_id=%s doc_chars=%s",
                project_id,
                session_id,
                len(current_document),
            )

        if user_input:
            session["last_user_input"] = user_input

        session.pop("last_error", None)

        return session

    def finish_session(self, project: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        project_id = str(project.get("id", "-"))
        session_id = str(session.get("id", "-"))
        history = list(session.get("history", []))
        previous_document = str(session.get("current_document", ""))

        config = self.config_manager.load()
        prompt_settings = self._get_prompt_settings(config)
        project_doc_path = project.get("project_doc_path") or config["doc_paths"]["project_doc"]
        project_doc_content = load_project_document(project["folder"], project_doc_path) or ""
        proactive_push_enabled = bool(project.get("proactive_push_enabled", False))
        proactive_push_branch = str(project.get("proactive_push_branch", "")).strip()

        session_context_text = self._build_session_context_text(
            session_name=str(session.get("name", "当前会话")),
            history=history,
        )

        try:
            final_document = self._generate_final_document(
                config=config,
                prompt_settings=prompt_settings,
                project_doc_content=project_doc_content,
                user_input="用户点击“保存对话并生成Agent开发文档”按钮，要求基于当前会话完整上下文输出最新文档。",
                question_and_input=session_context_text,
                project_id=project_id,
                session_id=session_id,
                stage="finish_final_doc",
            )
        except Exception as exc:
            session["is_complete"] = False
            session["user_confirmed_complete"] = False
            session["current_question"] = {
                "question": "AI 调用失败，暂未生成Agent开发文档，请检查日志后重试。",
                "options": [],
            }
            session["last_error"] = str(exc)
            self.system_logger.error(
                "dialog_finish_failed project_id=%s session_id=%s error=%s",
                project_id,
                session_id,
                exc,
            )
            return session

        final_document = ensure_required_sections(final_document, previous_document=previous_document)
        final_document = apply_contextual_instructions(
            final_document,
            project_name=project.get("name", "未命名项目"),
            history=history,
            config=config,
            project_doc_path=project_doc_path,
            proactive_push_enabled=proactive_push_enabled,
            proactive_push_branch=proactive_push_branch,
        )

        session["current_document"] = final_document
        session["is_complete"] = True
        session["ai_thinks_clear"] = True
        session["user_confirmed_complete"] = True
        session["current_question"] = {
            "question": "已保存当前会话并生成Agent开发文档。你仍可继续补充新需求，系统将重新进入澄清循环。",
            "options": [],
        }
        session["pending_questions"] = []
        session["unresolved_points"] = []
        session.pop("last_error", None)
        self.system_logger.info(
            "dialog_session_finished project_id=%s session_id=%s doc_chars=%s",
            project_id,
            session_id,
            len(session.get("current_document", "")),
        )
        return session

    def _run_ai_round(
        self,
        *,
        config: dict[str, Any],
        prompt_settings: dict[str, Any],
        project_doc_content: str,
        user_input: str,
        history: list[dict[str, Any]],
        session_context_text: str,
        project_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        placeholders = prompt_settings.get("placeholders", {})
        markers = prompt_settings.get("markers", {})

        question_open = str(markers.get("question_open", "<question>"))
        question_close = str(markers.get("question_close", "</question>"))
        option_open = str(markers.get("option_open", "<option>"))
        option_close = str(markers.get("option_close", "</option>"))

        qa_text = session_context_text.strip() or self._build_question_and_input_text(history)

        try:
            clarify_prompt = self._render_template(
                str(prompt_settings.get("clarify_prompt_template", "")),
                placeholders=placeholders,
                project_document=project_doc_content,
                user_input=user_input,
                question_and_input=qa_text,
            )
            clarify_raw = self._query_llm(
                api_config=config.get("api", {}),
                prompt=clarify_prompt,
                stage="clarify",
                project_id=project_id,
                session_id=session_id,
            )

            parsed_questions = parse_questions_and_options(
                clarify_raw,
                question_open=question_open,
                question_close=question_close,
                option_open=option_open,
                option_close=option_close,
            )

            questions = self._generate_options_in_parallel(
                config=config,
                prompt_settings=prompt_settings,
                placeholders=placeholders,
                parsed_questions=parsed_questions,
                qa_text=qa_text,
                option_open=option_open,
                option_close=option_close,
                project_id=project_id,
                session_id=session_id,
            )

            if questions:
                return {"questions": questions, "document_markdown": "", "error": ""}

            final_doc = self._generate_final_document(
                config=config,
                prompt_settings=prompt_settings,
                project_doc_content=project_doc_content,
                user_input=user_input,
                question_and_input=qa_text,
                project_id=project_id,
                session_id=session_id,
                stage="final_doc",
            )
            return {"questions": [], "document_markdown": final_doc, "error": ""}
        except Exception as exc:
            self.system_logger.exception(
                "dialog_round_failed project_id=%s session_id=%s",
                project_id,
                session_id,
            )
            return {"questions": [], "document_markdown": "", "error": str(exc)}

    def _generate_options_in_parallel(
        self,
        *,
        config: dict[str, Any],
        prompt_settings: dict[str, Any],
        placeholders: dict[str, Any],
        parsed_questions: list[dict[str, Any]],
        qa_text: str,
        option_open: str,
        option_close: str,
        project_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        candidates: list[tuple[int, str, list[str]]] = []
        for index, question_item in enumerate(parsed_questions):
            question = str(question_item.get("question", "")).strip()
            if not question:
                continue
            fallback_options = [str(item).strip() for item in question_item.get("options", []) if str(item).strip()]
            candidates.append((index, question, fallback_options))

        if not candidates:
            return []

        workers = min(self._resolve_concurrent_workers(config), len(candidates))
        results: list[tuple[int, dict[str, Any]]] = []

        if workers == 1:
            for index, question, fallback_options in candidates:
                options = self._generate_single_question_options(
                    config=config,
                    prompt_settings=prompt_settings,
                    placeholders=placeholders,
                    qa_text=qa_text,
                    question=question,
                    option_open=option_open,
                    option_close=option_close,
                    project_id=project_id,
                    session_id=session_id,
                    stage_suffix=f"options_{index + 1}",
                )
                if not options:
                    options = fallback_options
                results.append((index, {"question": question, "options": options[:6]}))

            return [payload for _, payload in sorted(results, key=lambda item: item[0])]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(
                    self._generate_single_question_options,
                    config=config,
                    prompt_settings=prompt_settings,
                    placeholders=placeholders,
                    qa_text=qa_text,
                    question=question,
                    option_open=option_open,
                    option_close=option_close,
                    project_id=project_id,
                    session_id=session_id,
                    stage_suffix=f"options_{index + 1}",
                ): (index, question, fallback_options)
                for index, question, fallback_options in candidates
            }

            for future in as_completed(future_map):
                index, question, fallback_options = future_map[future]
                try:
                    options = future.result()
                except Exception as exc:
                    self.system_logger.warning(
                        "dialog_options_failed project_id=%s session_id=%s question_index=%s error=%s",
                        project_id,
                        session_id,
                        index,
                        exc,
                    )
                    options = []

                if not options:
                    options = fallback_options

                results.append((index, {"question": question, "options": options[:6]}))

        return [payload for _, payload in sorted(results, key=lambda item: item[0])]

    def _generate_single_question_options(
        self,
        *,
        config: dict[str, Any],
        prompt_settings: dict[str, Any],
        placeholders: dict[str, Any],
        qa_text: str,
        question: str,
        option_open: str,
        option_close: str,
        project_id: str,
        session_id: str,
        stage_suffix: str,
    ) -> list[str]:
        options_prompt = self._render_template(
            str(prompt_settings.get("options_prompt_template", "")),
            placeholders=placeholders,
            # 选项生成阶段仅使用当前会话历史，不注入项目文档与本轮输入上下文。
            project_document="",
            user_input="",
            question_and_input=f"{qa_text}\n\n[当前问题]\n{question}",
        )
        options_prompt += (
            f"\n\n请仅用标记输出该问题选项："
            f"{option_open}选项文本{option_close}。"
        )
        options_raw = self._query_llm(
            api_config=config.get("api", {}),
            prompt=options_prompt,
            stage=stage_suffix,
            project_id=project_id,
            session_id=session_id,
        )
        return parse_tag_values(options_raw, option_open, option_close)

    def _resolve_concurrent_workers(self, config: dict[str, Any]) -> int:
        generation = config.get("generation", {})
        raw_value = generation.get("concurrent_workers", 5)
        try:
            workers = int(raw_value)
        except (TypeError, ValueError):
            workers = 5
        return max(1, min(20, workers))

    def _generate_final_document(
        self,
        *,
        config: dict[str, Any],
        prompt_settings: dict[str, Any],
        project_doc_content: str,
        user_input: str,
        question_and_input: str,
        project_id: str,
        session_id: str,
        stage: str,
    ) -> str:
        placeholders = prompt_settings.get("placeholders", {})
        final_prompt = self._render_template(
            str(prompt_settings.get("final_doc_prompt_template", "")),
            placeholders=placeholders,
            project_document=project_doc_content,
            user_input=user_input,
            question_and_input=question_and_input,
        )
        final_prompt += (
            "\n\n请输出 Markdown 文档，并直接输出文档正文，不要输出解释。"
            "\n并确保至少包含以下一级标题："
            "\n# 项目功能清单\n# 项目细节\n# 代码架构与实现方式"
            "\n同时在文档中必须明确：将要开发的新功能、开发步骤、细节要求。"
        )
        final_raw = self._query_llm(
            api_config=config.get("api", {}),
            prompt=final_prompt,
            stage=stage,
            project_id=project_id,
            session_id=session_id,
        )
        return self._strip_code_fence(final_raw)

    def _query_llm(
        self,
        *,
        api_config: dict[str, Any],
        prompt: str,
        stage: str,
        project_id: str,
        session_id: str,
    ) -> str:
        client = LLMClient(
            url=str(api_config.get("url", "")),
            api_key=str(api_config.get("api_key", "")),
            model=str(api_config.get("model", "")),
            temperature=float(api_config.get("temperature", 0.7)),
            timeout=int(api_config.get("timeout", 60)),
            max_retries=int(api_config.get("max_retries", 2)),
        )
        messages = [{"role": "user", "content": prompt}]
        self.ai_logger.info(
            "dialog_ai_request project_id=%s session_id=%s stage=%s model=%s prompt=%s",
            project_id,
            session_id,
            stage,
            api_config.get("model", ""),
            prompt,
        )
        response = client.get_response(messages)
        if not str(response).strip():
            self.system_logger.error(
                "dialog_ai_empty_response project_id=%s session_id=%s stage=%s",
                project_id,
                session_id,
                stage,
            )
            raise RuntimeError(f"AI 在阶段 {stage} 未返回任何内容")

        self.ai_logger.info(
            "dialog_ai_response project_id=%s session_id=%s stage=%s response=%s",
            project_id,
            session_id,
            stage,
            response,
        )
        return response

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

    def _build_session_context_text(
        self,
        *,
        session_name: str,
        history: list[dict[str, Any]],
    ) -> str:
        normalized_name = session_name.strip() or "当前会话"
        history_text = self._build_question_and_input_text(history)
        if not history_text:
            return f"[当前会话] 名称: {normalized_name}\n[当前会话] 暂无历史"
        return f"[当前会话] 名称: {normalized_name}\n{history_text}"

    def _normalize_user_input(self, answer_payload: dict[str, Any]) -> str:
        if answer_payload.get("skip_question"):
            return "用户选择跳过该问题并不再提出"

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
