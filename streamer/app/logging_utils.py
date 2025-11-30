from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event, Thread

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class StructuredFormatter(logging.Formatter):
    """Emit unified log lines: timestamp | LEVEL | logger | file:line | event | request_id | payload."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        level = record.levelname.upper()
        logger_name = record.name or self.service_name
        request_id = getattr(record, "request_id", "-") or "-"
        location = "-"
        if getattr(record, "pathname", None) and getattr(record, "lineno", None):
            location = f"{Path(record.pathname).name}:{record.lineno}"
        event = getattr(record, "event", record.getMessage() or "log")

        payload: dict[str, object] = {}
        for key, value in record.__dict__.items():
            if key in _RESERVED or key in {"request_id", "event"}:
                continue
            payload[key] = value
        if record.getMessage():
            payload.setdefault("message", record.getMessage())
        payload.setdefault("service", self.service_name)
        serialized = json.dumps(payload, default=str, separators=(",", ":"))
        return f"{ts} | {level} | {logger_name} | {location} | {event} | {request_id} | {serialized}"


def resolve_log_level(default: str = "INFO") -> tuple[str, int]:
    """Normalize LOG_LEVEL to a valid logging level with a safe fallback."""

    level_name = os.getenv("LOG_LEVEL", default).upper()
    resolved = logging.getLevelName(level_name)
    if isinstance(resolved, str):
        level_name = default.upper()
        resolved = logging.getLevelName(level_name)
    return level_name, int(resolved)


def setup_logging(service_name: str, log_level: str = "INFO") -> None:
    log_level_name, log_level_value = resolve_log_level(log_level)
    log_to_file = os.getenv("LOG_TO_FILE", "false").lower() in {"1", "true", "yes"}
    log_dir = Path(os.getenv("LOG_DIR", "./logs"))
    max_bytes = int(os.getenv("LOG_MAX_BYTES", "5000000"))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))

    formatter = StructuredFormatter(service_name)
    handlers: list[logging.Handler] = []

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

    if log_to_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        logfile = log_dir / f"{service_name}_{datetime.now(UTC).date():%Y-%m-%d}.log"
        file_handler = RotatingFileHandler(logfile, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(level=log_level_value, handlers=handlers, force=True)

    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        noisy_logger = logging.getLogger(noisy)
        noisy_logger.handlers = []
        noisy_logger.propagate = True

    service_logger = logging.getLogger(service_name)
    service_logger.setLevel(log_level_value)
    logging.getLogger(service_name).info(
        "logging initialized",
        extra={
            "event": "logging.init",
            "log_level": log_level_name,
            "log_to_file": log_to_file,
            "log_dir": str(log_dir),
        },
    )


def start_heartbeat(logger: logging.Logger, service_name: str, interval_seconds: int = 60) -> Event:
    stop_event: Event = Event()

    def _run() -> None:
        while not stop_event.wait(interval_seconds):
            logger.debug(
                "heartbeat",
                extra={"event": "service.heartbeat", "service": service_name, "interval": interval_seconds},
            )
        logger.info("heartbeat stopped", extra={"event": "service.heartbeat.stop", "service": service_name})

    Thread(target=_run, name=f"{service_name}-heartbeat", daemon=True).start()
    return stop_event
