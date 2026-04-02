from __future__ import annotations

from backend.document.generator import (
    apply_contextual_instructions,
    ensure_docagent_governance_block,
    resolve_project_doc_path,
)


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


def test_resolve_project_doc_path_reads_global_config_only() -> None:
    config = {"doc_paths": {"project_doc": "docs/global/PROJECT.md"}}

    path = resolve_project_doc_path(
        project_name="DemoProject",
        config=config,
        project_doc_path="docs/project_override/PROJECT.md",
    )

    assert path == "docs/global/DemoProject.md"


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
        "workflow": {
            "proactive_push_instruction": "请你积极上传，每当开发完一个功能，则进行一次上传",
        },
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

    assert "请你积极上传，每当开发完一个功能，则进行一次上传" in content


def test_add_proactive_instruction_uses_global_text_even_with_branch() -> None:
    config = {
        "doc_paths": {"project_doc": "docs/project/PROJECT.md"},
        "workflow": {
            "proactive_push_instruction": "每开发完一个功能都要立即提交并上传",
        },
    }
    history = _build_history("需要在文档里强调积极上传，完成一个功能后自动推送")

    content = apply_contextual_instructions(
        BASE_DOCUMENT,
        project_name="DemoProject",
        history=history,
        config=config,
        proactive_push_enabled=True,
        proactive_push_branch="main",
    )

    assert "每开发完一个功能都要立即提交并上传" in content
    assert "main 分支" not in content


def test_add_proactive_instruction_uses_default_text_when_config_missing() -> None:
    config = {"doc_paths": {"project_doc": "docs/project/PROJECT.md"}}
    history = _build_history("请在文档里补充积极上传要求")

    content = apply_contextual_instructions(
        BASE_DOCUMENT,
        project_name="DemoProject",
        history=history,
        config=config,
        proactive_push_enabled=True,
        proactive_push_branch="",
    )

    assert "请你积极上传，每当开发完一个功能，则进行一次上传" in content


def test_ensure_docagent_governance_block_adds_required_paths_and_branch() -> None:
    content = ensure_docagent_governance_block(
        BASE_DOCUMENT,
        project_doc_path="docs/project/PROJECT.md",
        project_doc_exists=True,
        proactive_push_enabled=True,
        proactive_push_branch="release/v2",
        root_agent_doc_path="/tmp/demo/AGENT_DEVELOPMENT.md",
    )

    assert "## DocAgent固定规范" in content
    assert "项目开发文档路径：`docs/project/PROJECT.md`" in content
    assert "项目开发文档由开发项目的 Agent 负责维护" in content
    assert "每完成一个新功能后，都必须同步更新项目开发文档" in content
    assert "AGENT_DEVELOPMENT.md" in content
    assert "每完成一个新功能后，都必须立即提交并上传到 `release/v2` 分支" in content


def test_ensure_docagent_governance_block_handles_missing_project_doc_and_is_idempotent() -> None:
    once = ensure_docagent_governance_block(
        BASE_DOCUMENT,
        project_doc_path="docs/project/PROJECT.md",
        project_doc_exists=False,
        proactive_push_enabled=False,
        proactive_push_branch="",
        root_agent_doc_path="AGENT_DEVELOPMENT.md",
    )
    twice = ensure_docagent_governance_block(
        once,
        project_doc_path="docs/project/PROJECT.md",
        project_doc_exists=False,
        proactive_push_enabled=False,
        proactive_push_branch="",
        root_agent_doc_path="AGENT_DEVELOPMENT.md",
    )

    assert "尚不存在" in once
    assert "当前未启用“积极上传”要求" in once
    assert twice.count("## DocAgent固定规范") == 1


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
