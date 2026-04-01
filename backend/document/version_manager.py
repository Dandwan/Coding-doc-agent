from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path

from backend.utils.file_utils import ensure_dir, read_text, resolve_in_project, write_text


class VersionManager:
    def __init__(self, project_folder: str | Path, agent_doc_dir: str) -> None:
        root = Path(project_folder).expanduser().resolve()
        self.project_root = root
        self.version_dir = ensure_dir(resolve_in_project(root, agent_doc_dir))
        self.root_agent_doc_path = self.project_root / "AGENT_DEVELOPMENT.md"
        self.root_legacy_doc_path = self.project_root / "DEVELOPMENT.md"

    def save_version(self, content: str) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        file_name = f"{timestamp}_DEVELOPMENT.md"
        candidate = self.version_dir / file_name

        seq = 1
        while candidate.exists():
            file_name = f"{timestamp}_{seq:02d}_DEVELOPMENT.md"
            candidate = self.version_dir / file_name
            seq += 1

        write_text(candidate, content)
        write_text(self.version_dir / "DEVELOPMENT.md", content)
        write_text(self.root_agent_doc_path, content)
        write_text(self.root_legacy_doc_path, content)
        return file_name

    def list_versions(self) -> list[dict]:
        versions: list[dict] = []
        if not self.version_dir.exists():
            return versions

        files = sorted(
            self.version_dir.glob("*_DEVELOPMENT.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for file_path in files:
            stat = file_path.stat()
            versions.append(
                {
                    "file_name": file_path.name,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "size": stat.st_size,
                }
            )
        return versions

    def get_version_content(self, file_name: str) -> str:
        safe_name = Path(file_name).name
        path = self.version_dir / safe_name
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(safe_name)
        return read_text(path, "")

    def restore_version(self, file_name: str) -> str:
        content = self.get_version_content(file_name)
        write_text(self.version_dir / "DEVELOPMENT.md", content)
        write_text(self.root_agent_doc_path, content)
        write_text(self.root_legacy_doc_path, content)
        return content

    def compare_versions(self, source_name: str, target_name: str = "DEVELOPMENT.md") -> str:
        source_content = self.get_version_content(source_name)
        target_content = self.get_version_content(target_name)

        diff_lines = list(
            difflib.unified_diff(
                target_content.splitlines(),
                source_content.splitlines(),
                fromfile=target_name,
                tofile=source_name,
                lineterm="",
            )
        )
        if not diff_lines:
            return "# 无差异\n"
        return "\n".join(diff_lines)
