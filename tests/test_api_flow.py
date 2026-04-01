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

    new_root = tmp_path / "projects_root"
    save_resp = c.post(
        "/api/config",
        json={
            "projects_root": str(new_root),
            "api": {"model": "gpt-test"},
            "doc_paths": {"agent_doc_dir": "docs/agent_versions"},
            "workflow": {
                "proactive_push_enabled_default": True,
                "proactive_push_branch_default": "release/test",
            },
        },
    )
    assert save_resp.status_code == 200

    loaded = c.get("/api/config").json()
    assert loaded["projects_root"] == str(new_root)
    assert loaded["api"]["model"] == "gpt-test"
    assert loaded["doc_paths"]["agent_doc_dir"] == "docs/agent_versions"
    assert loaded["workflow"]["proactive_push_enabled_default"] is True
    assert loaded["workflow"]["proactive_push_branch_default"] == "release/test"


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


def test_session_answer_version_compare_and_restore(client: tuple[TestClient, Path], tmp_path: Path) -> None:
    c, _ = client

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
    assert "# 项目功能清单" in updated_session["current_document"]
    assert "# 项目细节" in updated_session["current_document"]
    assert "# 代码架构与实现方式" in updated_session["current_document"]
    assert "feature/snake-v2" in updated_session["current_document"]

    root_doc = folder / "AGENT_DEVELOPMENT.md"
    assert root_doc.exists()
    root_text = root_doc.read_text(encoding="utf-8")
    assert "# 项目功能清单" in root_text

    versions_resp = c.get(f"/api/projects/{project_id}/doc/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) >= 2

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


def test_reverify_when_new_requirements_after_complete(client: tuple[TestClient, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client
    folder = tmp_path / "reverify_project"
    created = _create_project(c, folder, name="ReverifyProject")
    project_id = created["id"]

    session_resp = c.post(f"/api/projects/{project_id}/sessions", json={"name": "完成后继续"})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    import backend.main as main  # noqa: WPS433

    calls = {"count": 0}

    def fake_query_llm(**kwargs):
        calls["count"] += 1
        return {
            "next_question": "请补充细节",
            "options": ["边界", "验收", "回归"],
            "unresolved_points": [],
            "document_markdown": "",
            "is_complete": True,
        }

    monkeypatch.setattr(main.conversation_service, "_query_llm", fake_query_llm)

    first = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": [], "text_input": "先完成基础版本", "skip_question": False},
    )
    assert first.status_code == 200
    first_session = first.json()["session"]
    assert first_session["is_complete"] is False

    second_ready = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": ["边界"], "text_input": "补充一轮后可收敛", "skip_question": False},
    )
    assert second_ready.status_code == 200
    second_ready_session = second_ready.json()["session"]
    assert second_ready_session["is_complete"] is True

    second = c.post(
        f"/api/projects/{project_id}/sessions/{session_id}/answer",
        json={"selected_options": ["继续细化功能"], "text_input": "新增联机排行榜需求", "skip_question": False},
    )
    assert second.status_code == 200
    second_session = second.json()["session"]

    assert calls["count"] == 3
    assert second_session["is_complete"] is False
    assert "新增需求影响范围确认" in second_session["unresolved_points"]
    assert "新增需求验收标准确认" in second_session["unresolved_points"]
