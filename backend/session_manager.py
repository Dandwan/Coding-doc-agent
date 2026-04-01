from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.utils.file_utils import ensure_dir, now_iso, read_json, write_json


class SessionNotFoundError(Exception):
    pass


class SessionManager:
    def __init__(self, project_folder: str | Path) -> None:
        self.project_folder = Path(project_folder).expanduser().resolve()
        self.sessions_dir = ensure_dir(self.project_folder / "sessions")

    def list_sessions(self) -> list[dict]:
        sessions: list[dict] = []
        for file_path in self.sessions_dir.glob("*.json"):
            data = read_json(file_path, {})
            if not data:
                continue
            sessions.append(
                {
                    "id": data.get("id"),
                    "name": data.get("name", "未命名会话"),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "is_complete": bool(data.get("is_complete", False)),
                }
            )
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    def create_session(
        self,
        name: str | None,
        project_name: str,
        *,
        proactive_push_enabled: bool = False,
        proactive_push_branch: str = "",
        root_agent_doc_path: str = "AGENT_DEVELOPMENT.md",
    ) -> dict:
        sid = uuid4().hex[:12]
        now = now_iso()

        display_name = name.strip() if name and name.strip() else f"新会话-{now[11:19].replace(':', '')}"
        first_question = {
            "question": "请先直接描述你的需求，我会重点找出其中不清晰或可能产生歧义的细节。",
            "options": [],
        }

        payload = {
            "id": sid,
            "name": display_name,
            "created_at": now,
            "updated_at": now,
            "history": [],
            "unresolved_points": [],
            "pending_questions": [],
            "current_question": first_question,
            "current_document": "",
            "ai_thinks_clear": False,
            "is_complete": False,
            "user_confirmed_complete": False,
            "current_version": None,
            "requirement_seeded": False,
        }

        self.save_session(sid, payload)
        return payload

    def get_session(self, session_id: str) -> dict:
        file_path = self._session_file(session_id)
        data = read_json(file_path, None)
        if not data:
            raise SessionNotFoundError(session_id)
        return data

    def save_session(self, session_id: str, payload: dict) -> dict:
        payload["updated_at"] = now_iso()
        file_path = self._session_file(session_id)
        write_json(file_path, payload)
        return payload

    def delete_session(self, session_id: str) -> None:
        file_path = self._session_file(session_id)
        if not file_path.exists():
            raise SessionNotFoundError(session_id)
        file_path.unlink()

    def rename_session(self, session_id: str, name: str) -> dict:
        if not name.strip():
            raise ValueError("会话名称不能为空")
        payload = self.get_session(session_id)
        payload["name"] = name.strip()
        return self.save_session(session_id, payload)

    def _session_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"
