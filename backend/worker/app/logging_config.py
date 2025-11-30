from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from shared.logging import StructuredFormatter, get_request_id


class RequestContextFilter(logging.Filter):
    """Attach request/context metadata to worker logs."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        record.service_name = getattr(record, "service_name", self.service_name)
        return True


def resolve_log_level(default: str = "INFO") -> tuple[str, int]:
    """Normalize LOG_LEVEL to a valid logging level and return its name + numeric value."""

    level_name = os.getenv("LOG_LEVEL", default).upper()
    resolved = logging.getLevelName(level_name)
    if isinstance(resolved, str):
        level_name = default.upper()
        resolved = logging.getLevelName(level_name)
    return level_name, int(resolved)


def setup_logging(service_name: str) -> None:
    """Configure stdout + optional file logging for the worker."""

    log_level_name, log_level = resolve_log_level()
    log_to_file = os.getenv("LOG_TO_FILE", "false").lower() in {"1", "true", "yes"}
    log_dir = Path(os.getenv("LOG_DIR", "./logs"))
    max_bytes = int(os.getenv("LOG_MAX_BYTES", "5000000"))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    formatter = StructuredFormatter(service_name)
    context_filter = RequestContextFilter(service_name)

    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    handlers.append(stream_handler)

    if log_to_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        logfile = log_dir / f"{service_name}_{datetime.now(UTC).date():%Y-%m-%d}.log"
        file_handler = RotatingFileHandler(logfile, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        handlers.append(file_handler)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy", "alembic"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True
    logging.getLogger("alembic").setLevel(logging.WARNING)

    service_logger = logging.getLogger(service_name)
    service_logger.setLevel(log_level)
    service_logger.propagate = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    service_logger.info(
        "logging initialized",
        extra={
            "event": "logging.init",
            "log_level": log_level_name,
            "log_to_file": log_to_file,
            "log_dir": str(log_dir),
        },
    )
