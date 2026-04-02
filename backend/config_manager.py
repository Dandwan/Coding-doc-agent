from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.utils.file_utils import ensure_dir, merge_dict, read_json, write_json


DEFAULT_PROACTIVE_PUSH_INSTRUCTION = "请你积极上传，每当开发完一个功能，则进行一次上传"


class ConfigManager:
    def __init__(self) -> None:
        self.config_dir = ensure_dir(Path.home() / ".docagent")
        self.config_path = self.config_dir / "config.json"
        self.projects_index_path = self.config_dir / "projects.json"
        self.software_root = Path(__file__).resolve().parent.parent
        self.default_template_path = self.software_root / "default_settings" / "config.default.json"

        self.default_config: dict[str, Any] = self._load_default_template()

    def _build_builtin_default_config(self) -> dict[str, Any]:
        return {
            "projects_root": str((Path.home() / "DocAgentProjects").resolve()),
            "api": {
                "url": "https://api.openai.com/v1/chat/completions",
                "api_key": "",
                "model": "gpt-4o-mini",
                "temperature": 0.7,
                "timeout": 60,
                "max_retries": 2,
            },
            "generation": {
                "concurrent_workers": 5,
            },
            "doc_paths": {
                "project_doc": "docs/project/PROJECT.md",
                "agent_doc_dir": "docs/agent",
            },
            "workflow": {
                "proactive_push_enabled_default": False,
                "proactive_push_branch_default": "",
                "proactive_push_instruction": DEFAULT_PROACTIVE_PUSH_INSTRUCTION,
            },
            "logging": {
                "root_dir": str((Path.home() / ".docagent" / "logs").resolve()),
                "console_level": "INFO",
                "enable_console": True,
            },
            "prompt_settings": {
                "clarify_prompt_template": (
                    "你是需求澄清助手。请基于以下上下文，识别仍不清晰且可能导致开发方向偏差的细节。"
                    "如果存在不清晰点，请仅使用标识符输出问题，格式为 <question>问题内容</question>。"
                    "若无不清晰点，不要输出任何 <question> 标签。\n\n"
                    "项目开发文档:\n</projectDocument>\n\n"
                    "用户本轮输入:\n</userInput>\n\n"
                    "历史问答:\n</questionAndInput>"
                ),
                "options_prompt_template": (
                    "你是需求澄清助手。请针对给定问题生成可供用户选择的选项。"
                    "仅使用 <option>选项内容</option> 输出，建议 3-5 条，互斥且可执行。\n\n"
                    "项目开发文档:\n</projectDocument>\n\n"
                    "用户本轮输入:\n</userInput>\n\n"
                    "历史问答:\n</questionAndInput>"
                ),
                "final_doc_prompt_template": (
                    "你是技术负责人。请基于上下文生成最终 Markdown 格式 Agent 开发文档。"
                    "文档必须包含：将要开发的新功能、开发步骤、细节要求；"
                    "并在“项目细节”中明确写出项目开发文档的维护要求、维护责任和文档位置；"
                    "同时明确最新 Agent 开发文档输出到项目根目录 `AGENT_DEVELOPMENT.md`；"
                    "若已启用积极上传，还要写清每完成一个功能就提交上传一次，以及上传到哪个分支（如果已提供分支）。\n\n"
                    "项目开发文档:\n</projectDocument>\n\n"
                    "用户本轮输入:\n</userInput>\n\n"
                    "历史问答:\n</questionAndInput>"
                ),
                "placeholders": {
                    "project_document": "</projectDocument>",
                    "user_input": "</userInput>",
                    "question_and_input": "</questionAndInput>",
                },
                "markers": {
                    "question_open": "<question>",
                    "question_close": "</question>",
                    "option_open": "<option>",
                    "option_close": "</option>",
                },
            },
        }

    def _load_default_template(self) -> dict[str, Any]:
        builtin = self._build_builtin_default_config()
        template = read_json(self.default_template_path, {})
        if isinstance(template, dict) and template:
            return merge_dict(builtin, template)
        return builtin

    def _ensure_user_config_exists(self) -> None:
        if self.config_path.exists():
            return

        template = read_json(self.default_template_path, {})
        if not isinstance(template, dict) or not template:
            template = self.default_config

        write_json(self.config_path, template)

    def load(self) -> dict[str, Any]:
        self._ensure_user_config_exists()
        config = read_json(self.config_path, {})
        merged = merge_dict(self.default_config, config)
        if merged != config:
            self.save(merged)
        return merged

    def save(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = merge_dict(self.default_config, config)
        write_json(self.config_path, merged)
        return merged

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        updated = merge_dict(current, patch)
        return self.save(updated)

    def load_projects_index(self) -> list[dict[str, Any]]:
        return read_json(self.projects_index_path, [])

    def save_projects_index(self, projects: list[dict[str, Any]]) -> None:
        write_json(self.projects_index_path, projects)
