from __future__ import annotations

import logging
import os

from .local_logging import StructuredFormatter, get_request_id


class RequestContextFilter(logging.Filter):
    """Attach request/context metadata to hedger logs."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        record.service_name = getattr(record, "service_name", self.service_name)
        return True


def resolve_log_level(default: str = "INFO") -> tuple[str, int]:
    """Normalize LOG_LEVEL/HEDGER_LOG_LEVEL to a valid logging level."""

    level = os.getenv("HEDGER_LOG_LEVEL")
    env_level = logging.getLevelName(level.upper()) if level else None
    if isinstance(env_level, int):
        return os.getenv("HEDGER_LOG_LEVEL", default).upper(), env_level
    level_name = default.upper()
    return level_name, int(logging.getLevelName(level_name))


def setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    level_name, level_value = resolve_log_level(level)
    root = logging.getLogger()
    root.setLevel(level_value)
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter(service_name))
    handler.addFilter(RequestContextFilter(service_name))
    root.handlers = [handler]

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler]
        logger.setLevel(level_value)
        logger.propagate = logger_name != "uvicorn.access"
    # Quiet overly chatty dependencies.
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    service_logger = logging.getLogger(service_name)
    service_logger.setLevel(level_value)
    service_logger.info(
        "logging initialized",
        extra={
            "event": "logging.init",
            "log_level": level_name,
            "log_to_file": False,
        },
    )
    return service_logger
