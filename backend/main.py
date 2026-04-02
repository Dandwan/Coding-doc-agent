from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.agent.conversation import ConversationService
from backend.config_manager import ConfigManager
from backend.logging_manager import LOG_MANAGER, get_logger
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
_initial_config = config_manager.load()
_log_period_dir = LOG_MANAGER.configure(_initial_config.get("logging", {}))
system_logger = get_logger("system")
api_logger = get_logger("api")
system_logger.info("DocAgent 服务已启动，日志目录: %s", _log_period_dir)

project_manager = ProjectManager(config_manager)
conversation_service = ConversationService(config_manager)


class PickFolderRequest(BaseModel):
    initial_dir: Optional[str] = None


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    rid = uuid4().hex[:12]
    request.state.request_id = rid
    started = time.perf_counter()

    client_host = request.client.host if request.client else "-"
    api_logger.info(
        "request_started id=%s method=%s path=%s query=%s content_length=%s client=%s",
        rid,
        request.method,
        request.url.path,
        request.url.query,
        request.headers.get("content-length", "0"),
        client_host,
    )

    try:
        response = await call_next(request)
    except Exception:
        cost_ms = (time.perf_counter() - started) * 1000
        api_logger.exception(
            "request_failed id=%s method=%s path=%s cost_ms=%.2f",
            rid,
            request.method,
            request.url.path,
            cost_ms,
        )
        raise

    cost_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-Id"] = rid
    api_logger.info(
        "request_finished id=%s method=%s path=%s status=%s cost_ms=%.2f",
        rid,
        request.method,
        request.url.path,
        response.status_code,
        cost_ms,
    )
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    rid = _request_id(request)
    api_logger.warning(
        "request_validation_error id=%s method=%s path=%s detail=%s",
        rid,
        request.method,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": "请求参数校验失败",
            "errors": exc.errors(),
            "request_id": rid,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    rid = _request_id(request)
    api_logger.warning(
        "http_exception id=%s method=%s path=%s status=%s detail=%s",
        rid,
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "request_id": rid,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = _request_id(request)
    system_logger.exception(
        "unhandled_exception id=%s method=%s path=%s",
        rid,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误，请查看日志。",
            "request_id": rid,
        },
    )


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
    patch = payload.model_dump(exclude_none=True)
    logging_patch = patch.get("logging", {})
    if "root_dir" in logging_patch and not str(logging_patch.get("root_dir", "")).strip():
        raise HTTPException(status_code=400, detail="日志保存根目录不能为空")

    updated = config_manager.update(patch)
    log_period_dir = LOG_MANAGER.configure(updated.get("logging", {}))
    system_logger.info("全局配置已更新，当前日志目录: %s", log_period_dir)
    return {
        **updated,
        "active_log_period_dir": str(log_period_dir),
    }


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

    try:
        created = project_manager.create_project(payload.name, folder)
    except OSError as exc:
        system_logger.error("project_create_failed name=%s folder=%s error=%s", payload.name, folder, exc)
        raise HTTPException(status_code=400, detail=f"项目创建失败: {exc}") from None

    system_logger.info(
        "project_created id=%s name=%s folder=%s",
        created.get("id"),
        created.get("name"),
        created.get("folder"),
    )
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
            proactive_push_use_global=payload.proactive_push_use_global,
            proactive_push_enabled=payload.proactive_push_enabled,
            proactive_push_branch=payload.proactive_push_branch,
        )
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    except OSError as exc:
        system_logger.error("project_update_failed id=%s error=%s", project_id, exc)
        raise HTTPException(status_code=400, detail=f"项目更新失败: {exc}") from None

    sessions = _session_manager(updated).list_sessions()
    system_logger.info("project_updated id=%s name=%s", project_id, updated.get("name"))
    return {**updated, "sessions": sessions}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    deleted = project_manager.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="项目不存在")
    system_logger.info("project_deleted id=%s", project_id)
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
    session = manager.create_session(
        payload.name,
        project.get("name", "未命名项目"),
        proactive_push_enabled=bool(project.get("proactive_push_enabled", False)),
        proactive_push_branch=str(project.get("proactive_push_branch", "")),
        root_agent_doc_path=Path(str(project.get("root_agent_doc_path", "AGENT_DEVELOPMENT.md"))).name,
    )

    if str(session.get("current_document", "")).strip():
        version_name = _version_manager(project).save_version(session["current_document"])
        session["current_version"] = version_name
    saved = manager.save_session(session["id"], session)
    system_logger.info("session_created project_id=%s session_id=%s", project_id, saved.get("id"))
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
        renamed = manager.rename_session(session_id, payload.name)
        system_logger.info("session_renamed project_id=%s session_id=%s", project_id, session_id)
        return renamed
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
    system_logger.info("session_deleted project_id=%s session_id=%s", project_id, session_id)
    return {"ok": True}


@app.post("/api/projects/{project_id}/sessions/{session_id}/answer", response_model=AnswerResponse)
def answer(project_id: str, session_id: str, payload: AnswerRequest) -> dict:
    project = _project_or_404(project_id)
    manager = _session_manager(project)

    try:
        session = manager.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在") from None

    project_sessions = manager.list_session_details()
    updated = conversation_service.process_answer(
        project,
        session,
        payload.model_dump(),
        project_sessions=project_sessions,
    )
    if str(updated.get("current_document", "")).strip():
        version_name = _version_manager(project).save_version(updated.get("current_document", ""))
        updated["current_version"] = version_name
    saved = manager.save_session(session_id, updated)
    system_logger.info(
        "session_answered project_id=%s session_id=%s is_complete=%s ai_thinks_clear=%s",
        project_id,
        session_id,
        bool(saved.get("is_complete", False)),
        bool(saved.get("ai_thinks_clear", False)),
    )

    if str(saved.get("last_error", "")).strip():
        raise HTTPException(status_code=502, detail=f"AI 调用失败: {saved['last_error']}")

    return {"session": saved}


@app.post("/api/projects/{project_id}/sessions/{session_id}/finish")
def finish_session(project_id: str, session_id: str) -> dict:
    project = _project_or_404(project_id)
    manager = _session_manager(project)

    try:
        session = manager.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在") from None

    finished = conversation_service.finish_session(session)
    if str(finished.get("current_document", "")).strip():
        version_name = _version_manager(project).save_version(finished.get("current_document", ""))
        finished["current_version"] = version_name

    saved = manager.save_session(session_id, finished)
    system_logger.info("session_finished project_id=%s session_id=%s", project_id, session_id)
    return saved


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
