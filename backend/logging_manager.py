from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.utils.file_utils import ensure_dir


class _LevelOnlyFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level


class _MinLevelFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.level


class LogManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._period_dir: Path | None = None
        self._root_logger_name = "docagent"
        self._typed_loggers = {
            "system": "docagent.system",
            "api": "docagent.api",
            "ai": "docagent.ai",
        }

    def configure(self, logging_config: dict[str, Any] | None) -> Path:
        config = logging_config or {}
        root_dir = self._resolve_root_dir(str(config.get("root_dir", "")).strip())
        period_dir = self._create_period_dir(root_dir)
        console_level = self._parse_level(config.get("console_level", "INFO"), logging.INFO)
        enable_console = bool(config.get("enable_console", True))

        with self._lock:
            root_logger = logging.getLogger(self._root_logger_name)
            root_logger.setLevel(logging.DEBUG)
            root_logger.propagate = False
            self._clear_handlers(root_logger)

            for logger_name in self._typed_loggers.values():
                typed_logger = logging.getLogger(logger_name)
                typed_logger.setLevel(logging.DEBUG)
                typed_logger.propagate = True
                self._clear_handlers(typed_logger)

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            if enable_console:
                console_handler = logging.StreamHandler()
                console_handler.setLevel(console_level)
                console_handler.setFormatter(formatter)
                root_logger.addHandler(console_handler)

            level_dir = ensure_dir(period_dir / "levels")
            type_dir = ensure_dir(period_dir / "types")

            debug_handler = logging.FileHandler(level_dir / "debug.log", encoding="utf-8")
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.addFilter(_LevelOnlyFilter(logging.DEBUG))
            debug_handler.setFormatter(formatter)
            root_logger.addHandler(debug_handler)

            info_handler = logging.FileHandler(level_dir / "info.log", encoding="utf-8")
            info_handler.setLevel(logging.INFO)
            info_handler.addFilter(_LevelOnlyFilter(logging.INFO))
            info_handler.setFormatter(formatter)
            root_logger.addHandler(info_handler)

            warning_handler = logging.FileHandler(level_dir / "warning.log", encoding="utf-8")
            warning_handler.setLevel(logging.WARNING)
            warning_handler.addFilter(_LevelOnlyFilter(logging.WARNING))
            warning_handler.setFormatter(formatter)
            root_logger.addHandler(warning_handler)

            error_handler = logging.FileHandler(level_dir / "error.log", encoding="utf-8")
            error_handler.setLevel(logging.ERROR)
            error_handler.addFilter(_MinLevelFilter(logging.ERROR))
            error_handler.setFormatter(formatter)
            root_logger.addHandler(error_handler)

            for type_name, logger_name in self._typed_loggers.items():
                file_handler = logging.FileHandler(type_dir / f"{type_name}.log", encoding="utf-8")
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                logging.getLogger(logger_name).addHandler(file_handler)

            self._period_dir = period_dir

        get_logger("system").info("日志系统已配置，日志目录: %s", period_dir)
        return period_dir

    def get_period_dir(self) -> Path | None:
        return self._period_dir

    def _resolve_root_dir(self, raw_root_dir: str) -> Path:
        if raw_root_dir:
            candidate = Path(raw_root_dir).expanduser()
        else:
            candidate = Path.home() / ".docagent" / "logs"

        try:
            return ensure_dir(candidate.resolve())
        except OSError:
            fallback = ensure_dir((Path.home() / ".docagent" / "logs").resolve())
            return fallback

    def _create_period_dir(self, root_dir: Path) -> Path:
        now = datetime.now()
        return ensure_dir(root_dir / now.strftime("%Y-%m-%d") / now.strftime("%H%M%S"))

    def _clear_handlers(self, logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass

    def _parse_level(self, raw_level: Any, default: int) -> int:
        if isinstance(raw_level, int):
            return raw_level

        level_name = str(raw_level or "").upper()
        parsed = getattr(logging, level_name, None)
        if isinstance(parsed, int):
            return parsed
        return default


LOG_MANAGER = LogManager()


def get_logger(kind: str) -> logging.Logger:
    normalized = (kind or "system").strip().lower()
    if normalized in {"system", "api", "ai"}:
        return logging.getLogger(f"docagent.{normalized}")
    return logging.getLogger("docagent.system")
