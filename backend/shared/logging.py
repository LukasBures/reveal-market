from __future__ import annotations

import logging
import os
from contextvars import ContextVar, Token

from pythonjsonlogger import jsonlogger

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Attach request_id context to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get() or "-"
        record.cache_hit = getattr(record, "cache_hit", None)
        record.duration_ms = getattr(record, "duration_ms", None)
        record.event = getattr(record, "event", record.getMessage())
        return True


def configure_json_logging(service_name: str) -> None:
    """Configure structured JSON logging for the given service."""

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(event)s %(message)s %(request_id)s %(cache_hit)s %(duration_ms)s",
        rename_fields={
            "levelname": "level",
            "name": "logger",
            "asctime": "timestamp",
        },
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    logging.basicConfig(level=level, handlers=[handler], force=True)

    # Align third-party loggers with our handler.
    for third_party in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy"):
        logging.getLogger(third_party).handlers = []
        logging.getLogger(third_party).propagate = True
    logging.getLogger(service_name).propagate = True


def set_request_id(request_id: str) -> Token:
    """Store the current request identifier in the logging context."""

    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token) -> None:
    """Reset the stored request identifier after a request completes."""

    _request_id_ctx.reset(token)


def get_request_id() -> str | None:
    """Return the request identifier currently in scope."""

    return _request_id_ctx.get()


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **fields: object,
) -> None:
    """Emit a structured log with a consistent event field."""

    extra = {"event": event}
    extra.update(fields)
    logger.log(level, message, extra=extra)
