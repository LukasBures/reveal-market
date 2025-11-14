from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from shared.logging import get_request_id

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class RequestContextFilter(logging.Filter):
    """Attach request/context metadata to worker logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        record.request_id = request_id

        if getattr(record, "_request_appended", False):
            return True

        message = record.getMessage()
        record.msg = f"{message} | request_id={request_id}"
        record.args = None
        record._request_appended = True
        return True


def setup_logging(service_name: str) -> None:
    """Configure stdout + optional file logging for the worker."""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_to_file = os.getenv("LOG_TO_FILE", "false").lower() in {"1", "true", "yes"}
    log_dir = Path(os.getenv("LOG_DIR", "./logs"))
    max_bytes = int(os.getenv("LOG_MAX_BYTES", "5000000"))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    context_filter = RequestContextFilter()

    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    handlers.append(stream_handler)

    if log_to_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        logfile = log_dir / f"{service_name}_{datetime.utcnow().date():%Y-%m-%d}.log"
        file_handler = RotatingFileHandler(logfile, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        handlers.append(file_handler)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True

    logging.getLogger(service_name).propagate = True
    logging.getLogger(service_name).info(
        "logging initialized",
        extra={"event": "logging.init", "log_to_file": log_to_file, "log_dir": str(log_dir)},
    )
