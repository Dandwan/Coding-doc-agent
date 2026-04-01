from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


BASE = "http://127.0.0.1:8012"
TEST_ROOT = Path(r"C:\Users\Dandwan\Downloads\test")
PROJECT_FOLDER = TEST_ROOT / "DocAgentSnakeProject"
PROJECT_DOC = PROJECT_FOLDER / "docs" / "project" / "PROJECT.md"
HTTP_TIMEOUT = 360


def api(method: str, path: str, *, expected: int = 200, **kwargs: Any) -> Any:
    resp = requests.request(method, f"{BASE}{path}", timeout=HTTP_TIMEOUT, **kwargs)
    if resp.status_code != expected:
        raise RuntimeError(f"{method} {path} failed: {resp.status_code} {resp.text}")
    if "application/json" in resp.headers.get("content-type", ""):
        return resp.json()
    return resp.text


def ensure_project_doc() -> None:
    PROJECT_DOC.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_DOC.write_text(
        """# Python 贪吃蛇项目开发文档

## 已有设定
- 使用 Python 3.9+
- 图形界面优先考虑 pygame
- 核心规则：网格地图、碰撞判定、食物随机刷新、分数记录

## 目标
- 实现可运行的贪吃蛇游戏
- 支持暂停/继续、重新开始、最高分记录
""",
        encoding="utf-8",
    )


def choose_first_option(session: dict[str, Any]) -> list[str]:
    options = session.get("current_question", {}).get("options", [])
    if not options:
        return []
    return [str(options[0])]


def main() -> None:
    api_key = os.environ.get("DOCAGENT_TEST_API_KEY", "").strip()
    model = os.environ.get("DOCAGENT_TEST_MODEL", "deepseek-reasoner").strip()
    base_url = os.environ.get("DOCAGENT_TEST_API_URL", "https://api.deepseek.com/chat/completions").strip()

    if not api_key:
        raise RuntimeError("缺少 DOCAGENT_TEST_API_KEY")

    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECT_FOLDER.mkdir(parents=True, exist_ok=True)

    health = api("GET", "/api/health")

    config_payload = {
        "projects_root": str(TEST_ROOT),
        "api": {
            "url": base_url,
            "api_key": api_key,
            "model": model,
            "temperature": 0.7,
            "timeout": 45,
            "max_retries": 1,
        },
        "doc_paths": {
            "project_doc": "docs/project/PROJECT.md",
            "agent_doc_dir": "docs/agent",
        },
    }
    config = api("POST", "/api/config", json=config_payload)

    project = api(
        "POST",
        "/api/projects",
        json={
            "name": "Python贪吃蛇主题全功能测试",
            "folder": str(PROJECT_FOLDER),
        },
    )
    project_id = project["id"]

    detail_before = api("GET", f"/api/projects/{project_id}")

    # 用绝对路径覆盖项目开发文档配置，验证绝对路径能力。
    detail_after_patch = api(
        "PATCH",
        f"/api/projects/{project_id}",
        json={"project_doc_path": str(PROJECT_DOC)},
    )

    ensure_project_doc()
    detail_after_doc = api("GET", f"/api/projects/{project_id}")

    session = api("POST", f"/api/projects/{project_id}/sessions", json={"name": "贪吃蛇需求澄清"})
    session_id = session["id"]

    answers = [
        "目标用户是 Python 初学者和教学场景，强调可读性和可扩展性。",
        "输入使用方向键，输出包含实时分数、最高分和游戏状态提示。",
        "要求在 Windows/macOS 上可运行，响应流畅，单帧计算稳定。",
    ]

    llm_error_count = 0
    last_session = session
    for text in answers:
        payload = {
            "selected_options": choose_first_option(last_session),
            "text_input": text,
            "skip_question": False,
        }
        answer_resp = api("POST", f"/api/projects/{project_id}/sessions/{session_id}/answer", json=payload)
        last_session = answer_resp["session"]
        if last_session.get("last_error"):
            llm_error_count += 1

    versions = api("GET", f"/api/projects/{project_id}/doc/versions")
    latest_version = versions[0]["file_name"] if versions else ""
    oldest_version = versions[-1]["file_name"] if versions else ""

    viewed = api("GET", f"/api/projects/{project_id}/doc/versions/{latest_version}") if latest_version else {"content": ""}
    compared = (
        api("GET", f"/api/projects/{project_id}/doc/compare?source={oldest_version}&target=DEVELOPMENT.md")
        if oldest_version
        else {"diff": ""}
    )
    restored = (
        api(
            "POST",
            f"/api/projects/{project_id}/doc/versions/{oldest_version}/restore",
            json={"session_id": session_id},
        )
        if oldest_version
        else {"content": ""}
    )

    renamed = api(
        "PATCH",
        f"/api/projects/{project_id}/sessions/{session_id}",
        json={"name": "贪吃蛇会话-重命名验证"},
    )

    folder_open_resp = api("POST", f"/api/projects/{project_id}/folder/open")

    delete_session_resp = api("DELETE", f"/api/projects/{project_id}/sessions/{session_id}")
    sessions_after_delete = api("GET", f"/api/projects/{project_id}/sessions")

    summary = {
        "health": health,
        "config_projects_root": config.get("projects_root"),
        "project_id": project_id,
        "project_doc_exists_before": detail_before.get("project_doc_exists"),
        "project_doc_path_after_patch": detail_after_patch.get("project_doc_path"),
        "project_doc_exists_after": detail_after_doc.get("project_doc_exists"),
        "session_id": session_id,
        "history_count": len(last_session.get("history", [])),
        "is_complete": bool(last_session.get("is_complete")),
        "llm_error_count": llm_error_count,
        "version_count": len(versions),
        "latest_version": latest_version,
        "oldest_version": oldest_version,
        "viewed_has_required_headers": all(
            marker in viewed.get("content", "")
            for marker in ["# 项目功能清单", "# 项目细节", "# 代码架构与实现方式"]
        ),
        "compare_diff_non_empty": bool((compared.get("diff") or "").strip()),
        "restore_content_non_empty": bool((restored.get("content") or "").strip()),
        "rename_result": renamed.get("name"),
        "folder_open_ok": folder_open_resp.get("ok"),
        "delete_session_ok": delete_session_resp.get("ok"),
        "sessions_after_delete": len(sessions_after_delete),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
