from __future__ import annotations

from pathlib import Path

from backend.utils.file_utils import read_text, resolve_in_project


def load_project_document(project_folder: str | Path, project_doc_path: str) -> str | None:
    root = Path(project_folder).expanduser().resolve()
    target = resolve_in_project(root, project_doc_path)
    if not target.exists() or not target.is_file():
        return None

    content = read_text(target, "")
    if not content.strip():
        return None
    return content
