from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.agent.conversation import ConversationService
from backend.config_manager import ConfigManager
from backend.models import (
    AnswerRequest,
    AnswerResponse,
    AppConfigUpdate,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    RestoreVersionRequest,
    SessionCreateRequest,
    SessionRenameRequest,
)
from backend.document.version_manager import VersionManager
from backend.project_manager import ProjectManager, ProjectNotFoundError
from backend.session_manager import SessionManager, SessionNotFoundError


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="DocAgent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="assets")

config_manager = ConfigManager()
project_manager = ProjectManager(config_manager)
conversation_service = ConversationService(config_manager)


class PickFolderRequest(BaseModel):
    initial_dir: Optional[str] = None


def _project_or_404(project_id: str) -> dict:
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _session_manager(project: dict) -> SessionManager:
    return SessionManager(project["folder"])


def _version_manager(project: dict) -> VersionManager:
    config = config_manager.load()
    return VersionManager(project["folder"], config["doc_paths"]["agent_doc_dir"])


def _safe_folder_name(name: str) -> str:
    safe = re.sub(r"[\\/:*?\"<>|]", "_", name.strip())
    safe = re.sub(r"\s+", "_", safe)
    return safe or "DocAgentProject"


def _pick_folder_dialog(initial_dir: Optional[str]) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"当前环境不支持文件夹选择器: {exc}") from None

    initial = str(Path(initial_dir).expanduser()) if initial_dir else str(Path.home())

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    selected = filedialog.askdirectory(initialdir=initial, mustexist=False, title="选择文件夹")
    root.destroy()
    return str(Path(selected).resolve()) if selected else ""


@app.get("/", include_in_schema=False)
def index_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/project", include_in_schema=False)
def project_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "project.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "settings.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/system/pick-folder")
def pick_folder(payload: PickFolderRequest) -> dict:
    selected_path = _pick_folder_dialog(payload.initial_dir)
    return {
        "selected": bool(selected_path),
        "path": selected_path,
    }


@app.get("/api/config")
def get_config() -> dict:
    return config_manager.load()


@app.post("/api/config")
def save_config(payload: AppConfigUpdate) -> dict:
    updated = config_manager.update(payload.model_dump(exclude_none=True))
    return updated


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return project_manager.list_projects()


@app.post("/api/projects")
def create_project(payload: ProjectCreateRequest) -> dict:
    config = config_manager.load()
    folder = payload.folder.strip() if payload.folder and payload.folder.strip() else ""
    if not folder:
        root = Path(config["projects_root"]).expanduser().resolve()
        folder = str(root / _safe_folder_name(payload.name))

    created = project_manager.create_project(payload.name, folder)
    return created


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> dict:
    project = _project_or_404(project_id)
    sessions = _session_manager(project).list_sessions()
    return {**project, "sessions": sessions}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdateRequest) -> dict:
    try:
        updated = project_manager.update_project(
            project_id,
            name=payload.name,
            folder=payload.folder,
            project_doc_path=payload.project_doc_path,
        )
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None

    sessions = _session_manager(updated).list_sessions()
    return {**updated, "sessions": sessions}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    deleted = project_manager.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"ok": True}


@app.post("/api/projects/{project_id}/folder/open")
def open_project_folder(project_id: str) -> dict:
    try:
        project_manager.open_project_folder(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"目录不存在: {exc}") from None
    return {"ok": True}


@app.get("/api/projects/{project_id}/sessions")
def list_sessions(project_id: str) -> list[dict]:
    project = _project_or_404(project_id)
    return _session_manager(project).list_sessions()


@app.post("/api/projects/{project_id}/sessions")
def create_session(project_id: str, payload: SessionCreateRequest) -> dict:
    project = _project_or_404(project_id)
    manager = _session_manager(project)
    session = manager.create_session(payload.name, project.get("name", "未命名项目"))

    version_name = _version_manager(project).save_version(session["current_document"])
    session["current_version"] = version_name
    saved = manager.save_session(session["id"], session)
    return saved


@app.get("/api/projects/{project_id}/sessions/{session_id}")
def get_session(project_id: str, session_id: str) -> dict:
    project = _project_or_404(project_id)
    manager = _session_manager(project)
    try:
        return manager.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在") from None


@app.patch("/api/projects/{project_id}/sessions/{session_id}")
def rename_session(project_id: str, session_id: str, payload: SessionRenameRequest) -> dict:
    project = _project_or_404(project_id)
    manager = _session_manager(project)
    try:
        return manager.rename_session(session_id, payload.name)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.delete("/api/projects/{project_id}/sessions/{session_id}")
def delete_session(project_id: str, session_id: str) -> dict:
    project = _project_or_404(project_id)
    manager = _session_manager(project)
    try:
        manager.delete_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在") from None
    return {"ok": True}


@app.post("/api/projects/{project_id}/sessions/{session_id}/answer", response_model=AnswerResponse)
def answer(project_id: str, session_id: str, payload: AnswerRequest) -> dict:
    project = _project_or_404(project_id)
    manager = _session_manager(project)

    try:
        session = manager.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在") from None

    updated = conversation_service.process_answer(project, session, payload.model_dump())
    version_name = _version_manager(project).save_version(updated.get("current_document", ""))
    updated["current_version"] = version_name
    saved = manager.save_session(session_id, updated)
    return {"session": saved}


@app.get("/api/projects/{project_id}/doc/versions")
def list_doc_versions(project_id: str) -> list[dict]:
    project = _project_or_404(project_id)
    return _version_manager(project).list_versions()


@app.get("/api/projects/{project_id}/doc/versions/{version}")
def get_doc_version(project_id: str, version: str) -> dict:
    project = _project_or_404(project_id)
    manager = _version_manager(project)
    try:
        content = manager.get_version_content(version)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="版本不存在") from None
    return {"file_name": version, "content": content}


@app.get("/api/projects/{project_id}/doc/compare")
def compare_doc_versions(project_id: str, source: str, target: str = "DEVELOPMENT.md") -> dict:
    if not source.strip():
        raise HTTPException(status_code=400, detail="source 不能为空")

    project = _project_or_404(project_id)
    manager = _version_manager(project)
    try:
        diff = manager.compare_versions(source_name=source, target_name=target)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="版本不存在") from None

    return {"source": source, "target": target, "diff": diff}


@app.post("/api/projects/{project_id}/doc/versions/{version}/restore")
def restore_doc_version(project_id: str, version: str, payload: RestoreVersionRequest) -> dict:
    project = _project_or_404(project_id)
    manager = _version_manager(project)
    try:
        content = manager.restore_version(version)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="版本不存在") from None

    if payload.session_id:
        session_manager = _session_manager(project)
        try:
            session = session_manager.get_session(payload.session_id)
            session["current_document"] = content
            session["current_version"] = version
            session_manager.save_session(payload.session_id, session)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="会话不存在") from None

    return {"file_name": version, "content": content}
