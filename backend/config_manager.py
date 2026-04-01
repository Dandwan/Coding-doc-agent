from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.utils.file_utils import ensure_dir, merge_dict, read_json, write_json


class ConfigManager:
    def __init__(self) -> None:
        self.config_dir = ensure_dir(Path.home() / ".docagent")
        self.config_path = self.config_dir / "config.json"
        self.projects_index_path = self.config_dir / "projects.json"

        self.default_config: dict[str, Any] = {
            "projects_root": str((Path.home() / "DocAgentProjects").resolve()),
            "api": {
                "url": "https://api.openai.com/v1/chat/completions",
                "api_key": "",
                "model": "gpt-4o-mini",
                "temperature": 0.7,
                "timeout": 60,
                "max_retries": 2,
            },
            "doc_paths": {
                "project_doc": "docs/project/PROJECT.md",
                "agent_doc_dir": "docs/agent",
            },
        }

    def load(self) -> dict[str, Any]:
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
