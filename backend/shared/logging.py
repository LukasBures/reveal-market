from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import datetime
from threading import Event, Thread

_LOG_RECORD_RESERVED = {
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

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def configure_json_logging(service_name: str) -> None:  # pragma: no cover - legacy shim
    """Legacy helper retained for backwards compatibility.

    Services now configure logging via their own modules, but this prevents
    import errors during hot reloads if older processes still import the
    previous function.
    """

    logging.getLogger(service_name).warning(
        "configure_json_logging is deprecated; use service-specific logging_config.setup_logging() instead",
        extra={"event": "logging.deprecated"},
    )


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
    """Emit a formatted log message that embeds event metadata."""

    structured_fields = dict(fields)

    suffix = ""
    if structured_fields:
        serialized = " ".join(f"{key}={value}" for key, value in structured_fields.items())
        suffix = f" {serialized}"

    extra_fields = {key: value for key, value in structured_fields.items() if key not in _LOG_RECORD_RESERVED}
    extra_fields["event"] = event
    logger.log(level, f"[{event}] {message}{suffix}", extra=extra_fields)


class StructuredFormatter(logging.Formatter):
    """Formatter that emits unified log lines."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.utcnow().isoformat()
        level = record.levelname.upper()
        event = getattr(record, "event", record.getMessage() or "log")
        payload: dict[str, object] = {}
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_RESERVED:
                continue
            payload[key] = value
        if "message" not in payload and record.getMessage():
            payload["message"] = record.getMessage()
        if "request_id" not in payload and hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if not payload:
            payload = {"message": record.getMessage() or ""}
        serialized = json.dumps(payload, default=str)
        return f"{timestamp} | {level} | {self.service_name} | {event} | {serialized}"


def start_heartbeat_logger(
    logger: logging.Logger,
    service_name: str,
    *,
    interval_seconds: int = 60,
    message: str | None = None,
) -> Event:
    """Start a background thread that logs a heartbeat every interval seconds."""

    stop_event: Event = Event()

    def _run() -> None:
        while not stop_event.is_set():
            log_event(
                logger,
                logging.INFO,
                event="service.heartbeat",
                message=message or f"{service_name} is alive",
                service=service_name,
                interval=interval_seconds,
            )
            if stop_event.wait(interval_seconds):
                break
        log_event(
            logger,
            logging.DEBUG,
            event="service.heartbeat.stop",
            message="heartbeat logger stopping",
            service=service_name,
        )

    thread = Thread(target=_run, name=f"{service_name}-heartbeat", daemon=True)
    thread.start()
    return stop_event
