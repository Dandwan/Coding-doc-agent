from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.agent.prompt_builder import build_system_prompt
from backend.agent.question_parser import parse_llm_json
from backend.api.llm_client import LLMClient
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
        requirement_seeded = bool(session.get("requirement_seeded", False))
        has_text = bool(str(answer_payload.get("text_input", "")).strip())
        has_options = bool(answer_payload.get("selected_options"))
        is_first_requirement_turn = (not requirement_seeded) and (not answer_payload.get("skip_question")) and (has_text or has_options)

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

        if is_first_requirement_turn:
            session["requirement_seeded"] = True

        if not session.get("unresolved_points"):
            seed_text = self._extract_first_requirement(history)
            session["unresolved_points"] = self._derive_ambiguity_points(seed_text)

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
                is_first_requirement_turn=is_first_requirement_turn,
            )
        except Exception as exc:
            llm_error = str(exc)

        if parsed is None:
            parsed = self._fallback_result(
                session,
                force_reverify=force_reverify,
                is_first_requirement_turn=is_first_requirement_turn,
            )

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
        elif is_first_requirement_turn:
            # 首轮输入需求后必须进入澄清阶段，不直接判定完成。
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
        is_first_requirement_turn: bool,
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
        first_requirement = self._extract_first_requirement(session.get("history", []))
        unresolved = session.get("unresolved_points", [])
        current_document = str(session.get("current_document", ""))
        if len(current_document) > 6000:
            current_document = current_document[:6000] + "\n\n[内容已截断]"

        user_prompt = {
            "recent_history": recent_history,
            "unresolved_points": unresolved,
            "first_requirement": first_requirement,
            "latest_answer": answer_text,
            "current_document": current_document,
            "force_reverify": force_reverify,
            "is_first_requirement_turn": is_first_requirement_turn,
        }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": str(user_prompt)},
        ]

        raw = client.get_response(messages)
        parsed = parse_llm_json(raw)
        return parsed

    def _fallback_result(
        self,
        session: dict[str, Any],
        *,
        force_reverify: bool = False,
        is_first_requirement_turn: bool = False,
    ) -> dict[str, Any]:
        if force_reverify:
            return {
                "next_question": "你新增的需求会影响哪些既有模块和接口？请逐项确认。",
                "options": ["功能边界影响", "数据结构影响", "API/交互影响", "测试与回归影响"],
                "unresolved_points": self._ensure_reverify_points(session.get("unresolved_points", [])),
                "document_markdown": "",
                "is_complete": False,
            }

        unresolved = list(session.get("unresolved_points", []))
        if not unresolved:
            first_requirement = self._extract_first_requirement(session.get("history", []))
            unresolved = self._derive_ambiguity_points(first_requirement)

        focus = unresolved[0] if unresolved else "需求目标与边界"
        question_prefix = "你给出的需求草案里" if is_first_requirement_turn else "当前需求中"
        question = f"{question_prefix}“{focus}”仍不够清晰，更接近哪种情况？"
        options = self._build_options_for_focus(focus)

        return {
            "next_question": question,
            "options": options,
            "unresolved_points": unresolved,
            "document_markdown": "",
            "is_complete": False,
        }

    def _fallback_unresolved(self, unresolved_points: list[str], answer_payload: dict[str, Any]) -> list[str]:
        unresolved = list(unresolved_points)
        if not unresolved:
            unresolved = self._derive_ambiguity_points("")

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

        if text_input and not options:
            return text_input

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

    def _extract_first_requirement(self, history: list[dict[str, Any]]) -> str:
        for turn in history:
            if turn.get("skip_question"):
                continue
            text_input = str(turn.get("text_input", "")).strip()
            if text_input:
                return text_input

            answer = str(turn.get("answer", "")).strip()
            if answer:
                return re.sub(r"^(选项=|补充=)", "", answer)
        return ""

    def _derive_ambiguity_points(self, text: str) -> list[str]:
        points: list[str] = []
        normalized = text.lower()

        if not any(token in normalized for token in ["用户", "角色", "受众", "客户", "使用者"]):
            points.append("目标用户与使用角色")
        if not any(token in normalized for token in ["输入", "来源", "数据"]):
            points.append("输入来源与数据边界")
        if not any(token in normalized for token in ["输出", "结果", "导出", "展示"]):
            points.append("输出形式与交付标准")
        if not any(token in normalized for token in ["性能", "并发", "时延", "响应"]):
            points.append("性能指标与容量约束")
        if not any(token in normalized for token in ["部署", "运行", "环境", "平台", "系统"]):
            points.append("部署环境与运行约束")
        if not any(token in normalized for token in ["验收", "测试", "成功", "标准"]):
            points.append("验收标准与测试范围")

        if not points:
            points = ["边界条件与异常处理", "权限与安全约束"]
        return points

    def _build_options_for_focus(self, focus: str) -> list[str]:
        mapping = {
            "目标用户与使用角色": ["单一角色", "多角色协作", "内部团队", "外部客户"],
            "输入来源与数据边界": ["手工输入", "文件导入", "API 拉取", "数据库同步"],
            "输出形式与交付标准": ["Web 页面", "Markdown 文档", "JSON/API", "文件导出"],
            "性能指标与容量约束": ["秒级响应", "分钟级批处理", "高并发优先", "准确性优先"],
            "部署环境与运行约束": ["本地运行", "云服务器", "容器化", "混合部署"],
            "验收标准与测试范围": ["功能正确", "性能达标", "安全合规", "可维护性"],
            "边界条件与异常处理": ["失败重试", "降级兜底", "人工介入", "严格报错"],
            "权限与安全约束": ["无登录", "账号密码", "RBAC 权限", "审计日志"],
        }
        return mapping.get(focus, ["场景A", "场景B", "场景C", "需要你补充"])
