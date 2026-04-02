from __future__ import annotations

from pathlib import Path

from backend.config_manager import ConfigManager
from backend.utils.file_utils import read_json, write_json


def test_load_initializes_user_config_from_default_template(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    template_path = tmp_path / "default_settings" / "config.default.json"
    write_json(
        template_path,
        {
            "projects_root": str(tmp_path / "template_projects"),
            "api": {
                "url": "https://example.com/v1/chat/completions",
                "api_key": "",
                "model": "from-template-model",
                "temperature": 0.7,
                "timeout": 60,
                "max_retries": 2,
            },
            "generation": {
                "concurrent_workers": 9,
            },
            "doc_paths": {
                "project_doc": "docs/project/PROJECT.md",
                "agent_doc_dir": "docs/agent",
            },
            "workflow": {
                "proactive_push_enabled_default": False,
                "proactive_push_branch_default": "",
                "proactive_push_instruction": "模板积极上传文案",
            },
            "logging": {
                "root_dir": str(tmp_path / "template_logs"),
                "console_level": "INFO",
                "enable_console": True,
            },
            "prompt_settings": {
                "clarify_prompt_template": "clarify",
                "options_prompt_template": "options",
                "final_doc_prompt_template": "final",
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
        },
    )

    manager = ConfigManager()
    manager.default_template_path = template_path

    loaded = manager.load()
    saved = read_json(manager.config_path, {})

    assert manager.config_path.exists()
    assert loaded["api"]["model"] == "from-template-model"
    assert loaded["generation"]["concurrent_workers"] == 9
    assert loaded["workflow"]["proactive_push_instruction"] == "模板积极上传文案"
    assert saved["api"]["model"] == "from-template-model"
    assert saved["generation"]["concurrent_workers"] == 9
    assert saved["workflow"]["proactive_push_instruction"] == "模板积极上传文案"
