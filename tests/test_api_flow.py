from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient


def _fresh_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    for module_name in list(sys.modules):
        if module_name == "backend" or module_name.startswith("backend."):
            sys.modules.pop(module_name, None)

    import backend.main as main  # noqa: WPS433

    importlib.reload(main)
    return TestClient(main.app), fake_home


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Path]]:
    test_client, fake_home = _fresh_client(tmp_path, monkeypatch)
    with test_client as c:
        yield c, fake_home


def _create_project(client: TestClient, folder: Path, name: str = "DemoProject") -> dict:
    response = client.post(
        "/api/projects",
        json={"name": name, "folder": str(folder)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_config_read_and_update(client: tuple[TestClient, Path], tmp_path: Path) -> None:
    c, _ = client

    config_resp = c.get("/api/config")
    assert config_resp.status_code == 200
    config = config_resp.json()
    assert "projects_root" in config
    assert config["doc_paths"]["project_doc"] == "docs/project/PROJECT.md"
    assert config["generation"]["concurrent_workers"] == 5
    assert config["workflow"]["proactive_push_instruction"] == "请你积极上传，每当开发完一个功能，则进行一次上传"
    assert "logging" in config
    assert "root_dir" in config["logging"]

    new_root = tmp_path / "projects_root"
    save_resp = c.post(
        "/api/config",
        json={
            "projects_root": str(new_root),
            "api": {"model": "gpt-test"},
            "generation": {"concurrent_workers": 7},
            "doc_paths": {"agent_doc_dir": "docs/agent_versions"},
            "workflow": {
                "proactive_push_enabled_default": True,
                "proactive_push_branch_default": "release/test",
                "proactive_push_instruction": "每完成一个功能就立刻上传远程仓库",
            },
            "logging": {
                "root_dir": str(tmp_path / "logs"),
            },
        },
    )
    assert save_resp.status_code == 200

    loaded = c.get("/api/config").json()
    assert loaded["projects_root"] == str(new_root)
    assert loaded["api"]["model"] == "gpt-test"
    assert loaded["generation"]["concurrent_workers"] == 7
    assert loaded["doc_paths"]["agent_doc_dir"] == "docs/agent_versions"
    assert loaded["workflow"]["proactive_push_enabled_default"] is True
    assert loaded["workflow"]["proactive_push_branch_default"] == "release/test"
    assert loaded["workflow"]["proactive_push_instruction"] == "每完成一个功能就立刻上传远程仓库"
    assert loaded["logging"]["root_dir"] == str(tmp_path / "logs")
    assert "clarify_prompt_template" in loaded["prompt_settings"]
    assert "markers" in loaded["prompt_settings"]
    assert loaded["prompt_settings"]["markers"]["question_open"] == "<question>"


def test_create_project_keeps_existing_files(client: tuple[TestClient, Path], tmp_path: Path) -> None:
    c, _ = client

    folder = tmp_path / "existing_project"
    folder.mkdir(parents=True, exist_ok=True)
    sentinel = folder / "already_here.txt"
    sentinel.write_text("do not modify", encoding="utf-8")

    created = _create_project(c, folder, name="KeepFiles")

    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "do not modify"
    assert (folder / "meta.json").exists()
    assert (folder / "sessions").exists()

    detail_resp = c.get(f"/api/projects/{created['id']}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["project_doc_exists"] is False


def test_project_doc_exists_flag_updates(client: tuple[TestClient, Path], tmp_path: Path) -> None:
    c, _ = client

    folder = tmp_path / "doc_flag_project"
    created = _create_project(c, folder, name="DocFlag")

    detail_1 = c.get(f"/api/projects/{created['id']}").json()
    assert detail_1["project_doc_exists"] is False

    project_doc = folder / "docs" / "project" / "PROJECT.md"
    project_doc.parent.mkdir(parents=True, exist_ok=True)
    project_doc.write_text("# 项目开发文档\n\n已创建。", encoding="utf-8")

    detail_2 = c.get(f"/api/projects/{created['id']}").json()
    assert detail_2["project_doc_exists"] is True


def test_pick_folder_endpoint(client: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client

    import backend.main as main  # noqa: WPS433

    expected_path = r"C:\Users\Dandwan\Downloads\test"
    monkeypatch.setattr(main, "_pick_folder_dialog", lambda initial_dir: expected_path)

    resp = c.post("/api/system/pick-folder", json={"initial_dir": "C:\\"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["selected"] is True
    assert payload["path"] == expected_path


def test_logging_structure_created_after_config_update(client: tuple[TestClient, Path], tmp_path: Path) -> None:
    c, _ = client

    log_root = tmp_path / "runtime_logs"
    resp = c.post(
        "/api/config",
        json={
            "logging": {
                "root_dir": str(log_root),
                "console_level": "DEBUG",
            }
        },
    )
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["logging"]["root_dir"] == str(log_root)
    assert payload["active_log_period_dir"]

    period_dir = Path(payload["active_log_period_dir"])
    assert period_dir.exists()

    level_dir = period_dir / "levels"
    type_dir = period_dir / "types"
    assert (level_dir / "debug.log").exists()
    assert (level_dir / "info.log").exists()
    assert (level_dir / "warning.log").exists()
    assert (level_dir / "error.log").exists()
    assert (type_dir / "system.log").exists()
    assert (type_dir / "api.log").exists()
    assert (type_dir / "ai.log").exists()


def test_session_answer_version_compare_and_restore(client: tuple[TestClient, Path], tmp_path: Path) -> None:
    c, _ = client

    import backend.main as main  # noqa: WPS433

    state = {"clarify_count": 0}

    def fake_query_llm(*, api_config, prompt, **kwargs):
        if "请仅用标记输出该问题选项" in prompt:
            if "目标用户是谁" in prompt:
                return "<option>面向内部运营人员</option><option>面向普通终端用户</option><option>双角色协作</option>"
            return "<option>输入来自API</option><option>输入来自文件</option><option>输入来自手工录入</option>"

        if "请输出 Markdown 文档" in prompt:
            return (
                "# 项目功能清单\n\n"
                "- 新增需求：自动生成文档并保证方向一致\n\n"
                "# 项目细节\n\n"
                "## 开发步骤\n"
                "1. 需求澄清\n"
                "2. 模块实现\n"
                "3. 回归测试\n\n"
                "## 细节要求\n"
                "- 明确输入输出\n"
                "- 细化边界条件\n\n"
                "# 代码架构与实现方式\n"
                "- FastAPI + 原生前端\n"
            )

        state["clarify_count"] += 1
        if state["clarify_count"] == 1:
            return "<question>目标用户是谁？</question><question>输入输出边界是什么？</question>"
        if state["clarify_count"] == 2:
            return "需求已清晰，无需继续提问。"
        return "<question>新增需求会影响哪些现有模块？</question>"

    main.conversation_service._query_llm = fake_query_llm

    c.post(
        "/api/config",
        json={
            "workflow": {
                "proactive_push_enabled_default": True,
                "proactive_push_branch_default": "feature/default",
            }
        },
    )

    folder = tmp_path / "flow_project"
    created = _create_project(c, folder, name="FlowProject")
    project_id = created["id"]

    detail = c.get(f"/api/projects/{project_id}").json()
    assert detail["proactive_push_enabled"] is True
    assert detail["proactive_push_branch"] == "feature/default"

    patched = c.patch(
        f"/api/projects/{project_id}",
        json={
            "proactive_push_use_global": False,
            "proactive_push_enabled": True,
            "proactive_push_branch": "feature/snake-v2",
        },
    )
    assert patched.status_code == 200

    session_resp = c.post(f"/api/projects/{project_id}/sessions", json={"name": "需求澄清"})
    assert session_resp.status_code == 200
    session = session_resp.json()
    session_id = session["id"]
    assert session["current_question"]["options"] == []
    assert "先直接描述你的需求" in session["current_question"]["question"]

    answer_resp = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "优先自动生成文档，目标是减少需求遗漏", "skip_question": False},
    )
    assert answer_resp.status_code == 200, answer_resp.text
    updated_session = answer_resp.json()["session"]

    assert len(updated_session["history"]) == 1
    assert "options" in updated_session["history"][0]
    assert len(updated_session["history"][0]["options"]) == 2
    assert updated_session["current_document"] == ""
    assert updated_session["current_question"]["question"] == "目标用户是谁？"
    assert len(updated_session["current_question"]["options"]) >= 1

    q1_resp = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": ["双角色协作"], "text_input": "", "skip_question": False},
    )
    assert q1_resp.status_code == 200
    q1_session = q1_resp.json()["session"]
    assert q1_session["current_question"]["question"] == "输入输出边界是什么？"

    q2_resp = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": ["输入来自API"], "text_input": "输出为Markdown", "skip_question": False},
    )
    assert q2_resp.status_code == 200
    final_session = q2_resp.json()["session"]

    assert "# 项目功能清单" in final_session["current_document"]
    assert "# 项目细节" in final_session["current_document"]
    assert "# 代码架构与实现方式" in final_session["current_document"]
    assert final_session["ai_thinks_clear"] is True

    finish_resp = c.post(f"/api/projects/{project_id}/sessions/{session_id}/finish")
    assert finish_resp.status_code == 200
    finished = finish_resp.json()
    assert finished["is_complete"] is True
    assert finished["user_confirmed_complete"] is True

    reopen_resp = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "新增需求：加入权限分级", "skip_question": False},
    )
    assert reopen_resp.status_code == 200
    reopened = reopen_resp.json()["session"]
    assert reopened["is_complete"] is False
    assert reopened["current_question"]["question"] == "新增需求会影响哪些现有模块？"

    root_doc = folder / "AGENT_DEVELOPMENT.md"
    assert root_doc.exists()
    root_text = root_doc.read_text(encoding="utf-8")
    assert "# 项目功能清单" in root_text

    versions_resp = c.get(f"/api/projects/{project_id}/doc/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) >= 1

    source = versions[-1]["file_name"]
    compare_resp = c.get(
        f"/api/projects/{project_id}/doc/compare",
        params={"source": source, "target": "DEVELOPMENT.md"},
    )
    assert compare_resp.status_code == 200
    diff_text = compare_resp.json()["diff"]
    assert diff_text

    restore_resp = c.post(
        f"/api/projects/{project_id}/doc/versions/{source}/restore",
        json={"session_id": session_id},
    )
    assert restore_resp.status_code == 200
    restored = restore_resp.json()
    assert restored["file_name"] == source
    assert "content" in restored


def test_parallel_option_generation_tolerates_single_question_timeout(
    client: tuple[TestClient, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _ = client

    import backend.main as main  # noqa: WPS433

    def fake_query_llm(*, api_config, prompt, stage, **kwargs):
        if stage == "clarify":
            return (
                "<question>问题一：目标用户是谁？</question>"
                "<option>内部用户</option>"
                "<option>外部用户</option>"
                "<question>问题二：核心输入源是什么？</question>"
            )

        if stage == "options_1":
            raise RuntimeError("timeout")
        if stage == "options_2":
            return "<option>来自 API</option><option>来自文件</option><option>来自手工录入</option>"

        if stage == "final_doc":
            return (
                "# 项目功能清单\n\n"
                "- 并行选项生成容错\n\n"
                "# 项目细节\n\n"
                "- 单题失败不阻塞\n\n"
                "# 代码架构与实现方式\n\n"
                "- FastAPI\n"
            )
        return ""

    monkeypatch.setattr(main.conversation_service, "_query_llm", fake_query_llm)

    folder = tmp_path / "parallel_tolerance_project"
    created = _create_project(c, folder, name="ParallelTolerance")
    project_id = created["id"]

    c.post("/api/config", json={"generation": {"concurrent_workers": 4}})

    session_resp = c.post(f"/api/projects/{project_id}/sessions", json={"name": "并行容错"})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    answer_resp = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "请先识别歧义并生成选项", "skip_question": False},
    )
    assert answer_resp.status_code == 200, answer_resp.text

    updated_session = answer_resp.json()["session"]
    assert updated_session["current_question"]["question"] == "问题一：目标用户是谁？"
    assert updated_session["current_question"]["options"] == ["内部用户", "外部用户"]

    stored_options = updated_session["history"][0].get("options", [])
    assert len(stored_options) == 2
    assert stored_options[0]["question"] == "问题一：目标用户是谁？"
    assert stored_options[0]["options"] == ["内部用户", "外部用户"]
    assert stored_options[1]["question"] == "问题二：核心输入源是什么？"
    assert stored_options[1]["options"] == ["来自 API", "来自文件", "来自手工录入"]


def test_reverify_when_new_requirements_after_complete(client: tuple[TestClient, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client
    folder = tmp_path / "reverify_project"
    created = _create_project(c, folder, name="ReverifyProject")
    project_id = created["id"]

    session_resp = c.post(f"/api/projects/{project_id}/sessions", json={"name": "完成后继续"})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    import backend.main as main  # noqa: WPS433

    calls = {"clarify": 0}

    def fake_query_llm(*, api_config, prompt, **kwargs):
        if "请仅用标记输出该问题选项" in prompt:
            return "<option>场景A</option><option>场景B</option><option>场景C</option>"

        if "请输出 Markdown 文档" in prompt:
            return "# 项目功能清单\n\n- 已完成\n\n# 项目细节\n\n- 已明确\n\n# 代码架构与实现方式\n\n- 待实现"

        calls["clarify"] += 1
        if calls["clarify"] == 1:
            return "<question>请补充关键边界</question>"
        if calls["clarify"] == 2:
            return "需求已清晰，无需继续提问。"
        return "<question>新增需求影响范围</question>"

    monkeypatch.setattr(main.conversation_service, "_query_llm", fake_query_llm)

    first = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "先完成基础版本", "skip_question": False},
    )
    assert first.status_code == 200
    first_session = first.json()["session"]
    assert first_session["is_complete"] is False
    assert first_session["current_question"]["question"] == "请补充关键边界"

    second_ready = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": ["场景A"], "text_input": "补充一轮后可收敛", "skip_question": False},
    )
    assert second_ready.status_code == 200
    second_ready_session = second_ready.json()["session"]
    assert second_ready_session["is_complete"] is False
    assert second_ready_session["ai_thinks_clear"] is True

    finish_resp = c.post(f"/api/projects/{project_id}/sessions/{session_id}/finish")
    assert finish_resp.status_code == 200
    finished = finish_resp.json()
    assert finished["is_complete"] is True

    second = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "新增联机排行榜需求", "skip_question": False},
    )
    assert second.status_code == 200
    second_session = second.json()["session"]

    assert calls["clarify"] == 3
    assert second_session["is_complete"] is False
    assert "新增需求影响范围" in second_session["unresolved_points"]


def test_answer_returns_error_when_ai_output_empty(client: tuple[TestClient, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client
    folder = tmp_path / "empty_output_project"
    created = _create_project(c, folder, name="EmptyOutputProject")
    project_id = created["id"]

    session_resp = c.post(f"/api/projects/{project_id}/sessions", json={"name": "空输出检测"})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    import backend.main as main  # noqa: WPS433

    def fake_query_llm(*, api_config, prompt, **kwargs):
        raise RuntimeError("AI 在阶段 clarify 未返回任何内容")

    monkeypatch.setattr(main.conversation_service, "_query_llm", fake_query_llm)

    answer_resp = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "请帮我整理需求", "skip_question": False},
    )
    assert answer_resp.status_code == 502
    assert "AI 调用失败" in answer_resp.json().get("detail", "")


def test_session_context_is_isolated_across_sessions(
    client: tuple[TestClient, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _ = client
    folder = tmp_path / "session_isolated_context"
    created = _create_project(c, folder, name="ContextProject")
    project_id = created["id"]

    import backend.main as main  # noqa: WPS433

    clarify_prompts: list[str] = []

    def fake_query_llm(*, api_config, prompt, stage, **kwargs):
        if stage == "clarify":
            clarify_prompts.append(prompt)
            return "需求已清晰，无需继续提问。"
        if stage == "final_doc":
            return (
                "# 项目功能清单\n\n"
                "- 会话隔离上下文验证\n\n"
                "# 项目细节\n\n"
                "- 需要保留历史\n\n"
                "# 代码架构与实现方式\n\n"
                "- FastAPI\n"
            )
        return ""

    monkeypatch.setattr(main.conversation_service, "_query_llm", fake_query_llm)

    session_a = c.post(f"/api/projects/{project_id}/sessions", json={"name": "第一会话"})
    assert session_a.status_code == 200
    session_a_id = session_a.json()["id"]

    answer_a = c.post(
        f"/api/projects/{project_id}/sessions/{session_a_id}/answer",
        json={"selected_options": [], "text_input": "第一轮需求说明", "skip_question": False},
    )
    assert answer_a.status_code == 200

    session_b = c.post(f"/api/projects/{project_id}/sessions", json={"name": "第二会话"})
    assert session_b.status_code == 200
    session_b_id = session_b.json()["id"]

    answer_b = c.post(
        f"/api/projects/{project_id}/sessions/{session_b_id}/answer",
        json={"selected_options": [], "text_input": "第二轮需求说明", "skip_question": False},
    )
    assert answer_b.status_code == 200

    assert len(clarify_prompts) >= 2
    first_prompt = clarify_prompts[0]
    second_prompt = clarify_prompts[-1]

    assert "第一会话" in first_prompt
    assert "第一轮需求说明" in first_prompt

    assert "第二会话" in second_prompt
    assert "第二轮需求说明" in second_prompt
    assert "第一会话" not in second_prompt
    assert "第一轮需求说明" not in second_prompt


def test_finish_calls_ai_with_full_current_session_context(
    client: tuple[TestClient, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _ = client
    folder = tmp_path / "finish_ai_context"
    created = _create_project(c, folder, name="FinishAIContext")
    project_id = created["id"]

    session_resp = c.post(f"/api/projects/{project_id}/sessions", json={"name": "完整上下文会话"})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    import backend.main as main  # noqa: WPS433

    finish_prompts: list[str] = []

    def fake_query_llm(*, api_config, prompt, stage, **kwargs):
        if stage == "clarify":
            return "需求已清晰，无需继续提问。"
        if stage in {"final_doc", "finish_final_doc"}:
            if stage == "finish_final_doc":
                finish_prompts.append(prompt)
            return (
                "# 项目功能清单\n\n"
                "- 自动生成开发文档\n\n"
                "# 项目细节\n\n"
                "- 需要保留会话上下文\n\n"
                "# 代码架构与实现方式\n\n"
                "- FastAPI\n"
            )
        return ""

    monkeypatch.setattr(main.conversation_service, "_query_llm", fake_query_llm)

    first_answer = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "第一轮输入：需要自动生成文档", "skip_question": False},
    )
    assert first_answer.status_code == 200

    second_answer = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "第二轮输入：并保留同会话全部历史", "skip_question": False},
    )
    assert second_answer.status_code == 200

    finish_resp = c.post(f"/api/projects/{project_id}/sessions/{session_id}/finish")
    assert finish_resp.status_code == 200
    finished = finish_resp.json()

    assert finished["is_complete"] is True
    assert finish_prompts

    finish_prompt = finish_prompts[-1]
    assert "第一轮输入：需要自动生成文档" in finish_prompt
    assert "第二轮输入：并保留同会话全部历史" in finish_prompt
