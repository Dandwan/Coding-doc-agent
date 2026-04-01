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
ROOT_AGENT_DOC = PROJECT_FOLDER / "AGENT_DEVELOPMENT.md"
HTTP_TIMEOUT = 360


def api(method: str, path: str, *, expected: int = 200, **kwargs: Any) -> Any:
    resp = requests.request(method, f"{BASE}{path}", timeout=HTTP_TIMEOUT, **kwargs)
    if resp.status_code != expected:
        raise RuntimeError(f"{method} {path} failed: {resp.status_code} {resp.text}")
    if "application/json" in resp.headers.get("content-type", ""):
        return resp.json()
    return resp.text


def seed_existing_project_files() -> None:
    PROJECT_DOC.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_DOC.write_text(
        """# Python 贪吃蛇项目开发文档（已有内容）

## 已有设定
- 使用 Python 3.9+
- 图形界面优先考虑 pygame
- 核心规则：网格地图、碰撞判定、食物随机刷新、分数记录

## 已实现功能
- 单机模式
- 基础分数显示
- 游戏结束重开

## 目标
- 支持暂停/继续、重新开始、最高分记录
- 后续规划：排行榜与皮肤系统
""",
        encoding="utf-8",
    )

    ROOT_AGENT_DOC.write_text(
        """# 项目功能清单

- 已有：基础贪吃蛇单机玩法

# 项目细节

## 用户交互细节
- 键盘方向键

# 代码架构与实现方式

## 技术栈选型
- Python + pygame
""",
        encoding="utf-8",
    )


def choose_first_option(session: dict[str, Any]) -> list[str]:
    options = session.get("current_question", {}).get("options", [])
    if not options:
        return []
    return [str(options[0])]


def submit_answer(project_id: str, session: dict[str, Any], text: str) -> dict[str, Any]:
    payload = {
        "selected_options": choose_first_option(session),
        "text_input": text,
        "skip_question": False,
    }
    response = api(
        "POST",
        f"/api/projects/{project_id}/sessions/{session['id']}/answer",
        json=payload,
    )
    return response["session"]


def main() -> None:
    api_key = os.environ.get("DOCAGENT_TEST_API_KEY", "").strip()
    model = os.environ.get("DOCAGENT_TEST_MODEL", "deepseek-reasoner").strip()
    base_url = os.environ.get("DOCAGENT_TEST_API_URL", "https://api.deepseek.com/chat/completions").strip()

    if not api_key:
        raise RuntimeError("缺少 DOCAGENT_TEST_API_KEY")

    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECT_FOLDER.mkdir(parents=True, exist_ok=True)
    seed_existing_project_files()

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
        "workflow": {
            "proactive_push_enabled_default": True,
            "proactive_push_branch_default": "main",
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

    # 用绝对路径覆盖项目开发文档配置，并先继承全局积极上传默认值。
    detail_after_patch = api(
        "PATCH",
        f"/api/projects/{project_id}",
        json={
            "project_doc_path": str(PROJECT_DOC),
            "proactive_push_use_global": True,
        },
    )

    detail_after_doc = api("GET", f"/api/projects/{project_id}")

    # 场景A：已有项目 + 已有项目开发文档 + 新需求，生成新的 Agent 开发文档。
    session = api("POST", f"/api/projects/{project_id}/sessions", json={"name": "已有项目更新指南"})
    session_id = session["id"]

    answers = [
        "在已有单机版基础上，新增在线排行榜，并保持对 Python 初学者友好。",
        "增加皮肤系统与每日挑战模式，要求与现有分数系统兼容。",
        "继续保持 pygame 技术栈，输出更新指南供开发 Agent 执行。",
    ]

    llm_error_count = 0
    last_session = session
    for text in answers:
        last_session = submit_answer(project_id, last_session, text)
        if last_session.get("last_error"):
            llm_error_count += 1

    # 如果系统判定已完成，继续追加新需求，验证可继续更新并重新核实。
    round_guard = 0
    while not last_session.get("is_complete") and round_guard < 6:
        round_guard += 1
        last_session = submit_answer(project_id, last_session, f"补充核实细节回合 {round_guard}：请继续验证边界和验收。")
        if last_session.get("last_error"):
            llm_error_count += 1

    was_complete_before_new_requirement = bool(last_session.get("is_complete"))
    session_after_new_requirement = submit_answer(
        project_id,
        last_session,
        "新增需求：加入多人联机与观战模式，并要求保留离线单机玩法。",
    )
    if session_after_new_requirement.get("last_error"):
        llm_error_count += 1

    # 场景B：项目级覆盖积极上传（指定分支）。
    api(
        "PATCH",
        f"/api/projects/{project_id}",
        json={
            "proactive_push_use_global": False,
            "proactive_push_enabled": True,
            "proactive_push_branch": "feature/snake-updates",
        },
    )
    detail_branch_override = api("GET", f"/api/projects/{project_id}")

    branch_session = api("POST", f"/api/projects/{project_id}/sessions", json={"name": "积极上传-指定分支"})
    branch_session = submit_answer(project_id, branch_session, "请生成强调每个新功能提交并上传到指定分支的开发文档。")
    if branch_session.get("last_error"):
        llm_error_count += 1

    # 场景C：项目级覆盖积极上传（不指定分支）。
    api(
        "PATCH",
        f"/api/projects/{project_id}",
        json={
            "proactive_push_use_global": False,
            "proactive_push_enabled": True,
            "proactive_push_branch": "",
        },
    )
    detail_no_branch = api("GET", f"/api/projects/{project_id}")

    no_branch_session = api("POST", f"/api/projects/{project_id}/sessions", json={"name": "积极上传-不指定分支"})
    no_branch_session = submit_answer(project_id, no_branch_session, "请强调每个功能都提交上传，但不强调分支。")
    if no_branch_session.get("last_error"):
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

    root_doc_exists = ROOT_AGENT_DOC.exists()
    root_doc_content = ROOT_AGENT_DOC.read_text(encoding="utf-8") if root_doc_exists else ""

    update_doc_contains_new_requirement = (
        "多人联机" in session_after_new_requirement.get("current_document", "")
        or "观战" in session_after_new_requirement.get("current_document", "")
    )

    branch_doc = branch_session.get("current_document", "")
    no_branch_doc = no_branch_session.get("current_document", "")

    summary = {
        "health": health,
        "config_projects_root": config.get("projects_root"),
        "project_id": project_id,
        "project_doc_exists_before": detail_before.get("project_doc_exists"),
        "project_doc_path_after_patch": detail_after_patch.get("project_doc_path"),
        "project_doc_exists_after": detail_after_doc.get("project_doc_exists"),
        "global_proactive_push_default_enabled": config.get("workflow", {}).get("proactive_push_enabled_default"),
        "global_proactive_push_default_branch": config.get("workflow", {}).get("proactive_push_branch_default"),
        "session_id": session_id,
        "history_count": len(session_after_new_requirement.get("history", [])),
        "was_complete_before_new_requirement": was_complete_before_new_requirement,
        "is_complete_after_new_requirement": bool(session_after_new_requirement.get("is_complete")),
        "unresolved_count_after_new_requirement": len(session_after_new_requirement.get("unresolved_points", [])),
        "update_doc_contains_new_requirement_keyword": update_doc_contains_new_requirement,
        "llm_error_count": llm_error_count,
        "version_count": len(versions),
        "latest_version": latest_version,
        "oldest_version": oldest_version,
        "root_agent_doc_path": str(ROOT_AGENT_DOC),
        "root_agent_doc_exists": root_doc_exists,
        "root_doc_has_required_headers": all(
            marker in root_doc_content
            for marker in ["# 项目功能清单", "# 项目细节", "# 代码架构与实现方式"]
        ),
        "viewed_has_required_headers": all(
            marker in viewed.get("content", "")
            for marker in ["# 项目功能清单", "# 项目细节", "# 代码架构与实现方式"]
        ),
        "compare_diff_non_empty": bool((compared.get("diff") or "").strip()),
        "restore_content_non_empty": bool((restored.get("content") or "").strip()),
        "rename_result": renamed.get("name"),
        "project_override_with_branch_enabled": detail_branch_override.get("proactive_push_enabled"),
        "project_override_with_branch_name": detail_branch_override.get("proactive_push_branch"),
        "branch_doc_mentions_specific_branch": "feature/snake-updates" in branch_doc,
        "project_override_without_branch_enabled": detail_no_branch.get("proactive_push_enabled"),
        "project_override_without_branch_name": detail_no_branch.get("proactive_push_branch"),
        "no_branch_doc_mentions_specific_branch": "feature/snake-updates" in no_branch_doc,
        "folder_open_ok": folder_open_resp.get("ok"),
        "existing_project_doc_seeded": PROJECT_DOC.exists(),
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
