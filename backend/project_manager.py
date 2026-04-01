from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from backend.config_manager import ConfigManager
from backend.utils.file_utils import ensure_dir, now_iso, read_json, resolve_in_project, write_json


class ProjectNotFoundError(Exception):
    pass


class ProjectManager:
    def __init__(self, config_manager: ConfigManager) -> None:
        self.config_manager = config_manager

    def list_projects(self) -> list[dict]:
        projects = self.config_manager.load_projects_index()
        return sorted(projects, key=lambda x: x.get("updated_at", ""), reverse=True)

    def create_project(self, name: str, folder: str) -> dict:
        folder_path = Path(folder).expanduser().resolve()
        ensure_dir(folder_path)

        now = now_iso()
        meta_path = folder_path / "meta.json"
        old_meta = read_json(meta_path, {})

        project_id = old_meta.get("id") or uuid4().hex
        created_at = old_meta.get("created_at", now)

        meta = {
            "id": project_id,
            "name": name.strip() or old_meta.get("name", "未命名项目"),
            "created_at": created_at,
            "updated_at": now,
            "last_opened_at": now,
            "project_doc_path": old_meta.get("project_doc_path"),
        }
        write_json(meta_path, meta)

        self._ensure_managed_dirs(folder_path)

        projects = self.config_manager.load_projects_index()
        entry = {
            "id": project_id,
            "name": meta["name"],
            "folder": str(folder_path),
            "created_at": created_at,
            "updated_at": now,
        }

        replaced = False
        for i, project in enumerate(projects):
            if project.get("id") == project_id or Path(project.get("folder", "")).resolve() == folder_path:
                projects[i] = entry
                replaced = True
                break

        if not replaced:
            projects.append(entry)

        self.config_manager.save_projects_index(projects)
        return entry

    def get_project(self, project_id: str) -> dict | None:
        projects = self.config_manager.load_projects_index()
        for project in projects:
            if project.get("id") != project_id:
                continue

            folder = Path(project["folder"]).expanduser().resolve()
            meta_path = folder / "meta.json"
            meta = read_json(meta_path, {})
            if not meta:
                meta = {
                    "id": project_id,
                    "name": project.get("name", "未命名项目"),
                    "created_at": project.get("created_at", now_iso()),
                    "updated_at": project.get("updated_at", now_iso()),
                    "last_opened_at": now_iso(),
                    "project_doc_path": None,
                }

            meta["last_opened_at"] = now_iso()
            write_json(meta_path, meta)

            config = self.config_manager.load()
            project_doc_path = meta.get("project_doc_path") or config["doc_paths"]["project_doc"]
            project_doc_exists = resolve_in_project(folder, project_doc_path).exists()

            updated_project = {
                "id": project_id,
                "name": meta.get("name", project.get("name", "未命名项目")),
                "folder": str(folder),
                "created_at": meta.get("created_at", project.get("created_at", now_iso())),
                "updated_at": meta.get("updated_at", now_iso()),
                "last_opened_at": meta.get("last_opened_at", now_iso()),
                "project_doc_path": project_doc_path,
                "project_doc_exists": project_doc_exists,
            }
            return updated_project
        return None

    def delete_project(self, project_id: str) -> bool:
        projects = self.config_manager.load_projects_index()
        new_projects = [item for item in projects if item.get("id") != project_id]
        if len(new_projects) == len(projects):
            return False
        self.config_manager.save_projects_index(new_projects)
        return True

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        folder: str | None = None,
        project_doc_path: str | None = None,
    ) -> dict:
        projects = self.config_manager.load_projects_index()
        target_index = -1
        for i, item in enumerate(projects):
            if item.get("id") == project_id:
                target_index = i
                break

        if target_index < 0:
            raise ProjectNotFoundError(project_id)

        entry = projects[target_index]
        old_folder = Path(entry["folder"]).expanduser().resolve()
        target_folder = old_folder

        if folder and Path(folder).expanduser().resolve() != old_folder:
            target_folder = Path(folder).expanduser().resolve()
            self._move_managed_content(old_folder, target_folder)

        meta_path = target_folder / "meta.json"
        meta = read_json(meta_path, {})
        now = now_iso()

        if not meta:
            meta = {
                "id": project_id,
                "name": entry.get("name", "未命名项目"),
                "created_at": entry.get("created_at", now),
                "updated_at": now,
                "last_opened_at": now,
                "project_doc_path": None,
            }

        if name is not None and name.strip():
            meta["name"] = name.strip()
        if project_doc_path is not None:
            meta["project_doc_path"] = project_doc_path.strip() or None

        meta["updated_at"] = now
        write_json(meta_path, meta)

        self._ensure_managed_dirs(target_folder)

        updated_entry = {
            "id": project_id,
            "name": meta.get("name", entry.get("name", "未命名项目")),
            "folder": str(target_folder),
            "created_at": meta.get("created_at", entry.get("created_at", now)),
            "updated_at": now,
        }
        projects[target_index] = updated_entry
        self.config_manager.save_projects_index(projects)

        result = self.get_project(project_id)
        if result is None:
            raise ProjectNotFoundError(project_id)
        return result

    def open_project_folder(self, project_id: str) -> None:
        project = self.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)

        folder = Path(project["folder"])
        if not folder.exists():
            raise FileNotFoundError(str(folder))

        if os.name == "nt":
            os.startfile(str(folder))
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
            return
        subprocess.Popen(["xdg-open", str(folder)])

    def _ensure_managed_dirs(self, folder: Path) -> None:
        ensure_dir(folder / "sessions")
        config = self.config_manager.load()

        agent_doc_dir = resolve_in_project(folder, config["doc_paths"]["agent_doc_dir"])
        ensure_dir(agent_doc_dir)

        project_doc_path = resolve_in_project(folder, config["doc_paths"]["project_doc"])
        ensure_dir(project_doc_path.parent)

    def _move_managed_content(self, old_folder: Path, new_folder: Path) -> None:
        ensure_dir(new_folder)

        for item_name in ["meta.json", "sessions", "docs"]:
            src = old_folder / item_name
            dst = new_folder / item_name
            if src.exists():
                self._merge_move(src, dst)

    def _merge_move(self, src: Path, dst: Path) -> None:
        if src.is_file():
            ensure_dir(dst.parent)
            if dst.exists() and dst.is_file():
                dst.unlink()
            shutil.move(str(src), str(dst))
            return

        ensure_dir(dst)
        for child in src.iterdir():
            self._merge_move(child, dst / child.name)

        try:
            src.rmdir()
        except OSError:
            pass
