"""Structured logging configuration.

Uses Python's built-in ``logging`` module with JSON formatting for
production environments and standard human-readable formatting during
development.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from app.core.config import settings


class JSONFormatter(logging.Formatter):
    """Output log records as single-line JSON objects.

    Suitable for ingestion by structured-logging backends such as
    ELK, Loki, or CloudWatch.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


def configure_logging() -> None:
    """Set up the root logger according to the current environment."""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove any pre-existing handlers to avoid duplicates on reload.
    root.handlers.clear()

    # ── Console handler ──────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    if settings.is_production:
        console.setFormatter(JSONFormatter())
    else:
        console.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root.addHandler(console)

    # ── File handler (non-testing only) ──────────────────────────────
    if not settings.IS_TESTING:
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / "enwis.log",
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(JSONFormatter())
        root.addHandler(file_handler)

    # Keep third-party library loggers quiet unless they are noisy at
    # DEBUG — we intentionally let them through only at WARNING+.
    for lib in ("httpx", "httpcore", "asyncio", "aiosqlite"):
        logging.getLogger(lib).setLevel(logging.WARNING)
