from __future__ import annotations

from backend.document.generator import apply_contextual_instructions, resolve_project_doc_path


BASE_DOCUMENT = """# 项目功能清单

- 示例功能

# 项目细节

- 示例细节

# 代码架构与实现方式

- 示例架构
"""


def _build_history(*answers: str) -> list[dict]:
    return [
        {
            "answer": answer,
            "text_input": answer,
            "selected_options": [],
        }
        for answer in answers
    ]


def test_resolve_project_doc_path_replaces_placeholder() -> None:
    config = {"doc_paths": {"project_doc": "docs/project/PROJECT.md"}}

    path = resolve_project_doc_path(
        project_name="Doc Agent",
        config=config,
    )

    assert path == "docs/project/Doc-Agent.md"


def test_add_update_project_doc_instruction_with_resolved_path() -> None:
    config = {"doc_paths": {"project_doc": "docs/project/PROJECT.md"}}
    history = _build_history("请在AGENT_DEVELOPMENT.md中要求agent更新项目开发文档")

    content = apply_contextual_instructions(
        BASE_DOCUMENT,
        project_name="DemoProject",
        history=history,
        config=config,
        proactive_push_enabled=False,
    )

    assert "要求Agent更新项目开发文档" in content
    assert "docs/project/DemoProject.md" in content
    assert "项目概述" in content


def test_skip_proactive_instruction_when_disabled() -> None:
    config = {"doc_paths": {"project_doc": "docs/project/PROJECT.md"}}
    history = _build_history("请在文档里要求agent执行积极上传，在完成一个功能后自动推送")

    content = apply_contextual_instructions(
        BASE_DOCUMENT,
        project_name="DemoProject",
        history=history,
        config=config,
        proactive_push_enabled=False,
        proactive_push_branch="",
    )

    assert "要求Agent执行积极上传" not in content


def test_add_proactive_instruction_without_branch_when_enabled() -> None:
    config = {
        "doc_paths": {"project_doc": "docs/project/PROJECT.md"},
        "workflow": {"proactive_push_branch_default": ""},
    }
    history = _build_history("需要在文档里强调积极上传，完成一个功能后自动推送")

    content = apply_contextual_instructions(
        BASE_DOCUMENT,
        project_name="DemoProject",
        history=history,
        config=config,
        proactive_push_enabled=True,
        proactive_push_branch="",
    )

    assert "要求Agent执行积极上传，在完成一个功能后自动推送变更。" in content
    assert "推送到 " not in content


def test_add_proactive_instruction_with_branch_when_enabled() -> None:
    config = {"doc_paths": {"project_doc": "docs/project/PROJECT.md"}}
    history = _build_history("需要在文档里强调积极上传，完成一个功能后自动推送")

    content = apply_contextual_instructions(
        BASE_DOCUMENT,
        project_name="DemoProject",
        history=history,
        config=config,
        proactive_push_enabled=True,
        proactive_push_branch="main",
    )

    assert "要求Agent执行积极上传，在完成一个功能后自动将变更推送到 main 分支。" in content


def test_no_intent_keeps_document_unchanged() -> None:
    config = {"doc_paths": {"project_doc": "docs/project/PROJECT.md"}}
    history = _build_history("请补充接口字段定义")

    content = apply_contextual_instructions(
        BASE_DOCUMENT,
        project_name="DemoProject",
        history=history,
        config=config,
        proactive_push_enabled=True,
        proactive_push_branch="main",
    )

    assert content == BASE_DOCUMENT