from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
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

MAX_LINE_LEN = 0
MAX_PAYLOAD_LEN = 0

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> Token:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id_ctx.reset(token)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **fields: object,
) -> None:
    if not logger.isEnabledFor(level):
        return
    extra_fields = {key: value for key, value in fields.items() if key not in _LOG_RECORD_RESERVED}
    extra_fields["event"] = event
    logger.log(level, f"[{event}] {message}", extra=extra_fields)


class StructuredFormatter(logging.Formatter):
    """Emit unified log lines: timestamp | LEVEL | logger | file:line | event | payload."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        level = record.levelname.upper()
        logger_name = record.name or self.service_name
        pathname = getattr(record, "pathname", None)
        lineno = getattr(record, "lineno", None)
        location = f"{pathname.split('/')[-1]}:{lineno}" if pathname and lineno else "-"
        event = getattr(record, "event", record.getMessage() or "log")

        payload: dict[str, object] = {}
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_RESERVED or key in {"request_id", "event"}:
                continue
            payload[key] = value
        if record.getMessage():
            payload.setdefault("message", record.getMessage())
        payload.setdefault("service", self.service_name)

        serialized = json.dumps(payload, default=str, separators=(",", ":")) if payload else "{}"
        if MAX_PAYLOAD_LEN and len(serialized) > MAX_PAYLOAD_LEN:
            serialized = serialized[:MAX_PAYLOAD_LEN]
        line = f"{timestamp} | {level} | {logger_name} | {location} | {event} | {serialized}"
        if MAX_LINE_LEN and len(line) > MAX_LINE_LEN:
            allowed_payload_len = max(8, MAX_LINE_LEN - (len(line) - len(serialized)))
            if len(serialized) > allowed_payload_len:
                serialized = serialized[:allowed_payload_len]
                line = f"{timestamp} | {level} | {logger_name} | {location} | {event} | {serialized}"
        return line


def start_heartbeat_logger(
    logger: logging.Logger,
    service_name: str,
    *,
    interval_seconds: int = 60,
    message: str | None = None,
) -> Event:
    stop_event: Event = Event()

    def _run() -> None:
        while not stop_event.is_set():
            log_event(
                logger,
                logging.DEBUG,
                event="service.heartbeat",
                message=message or f"{service_name} is alive",
                service=service_name,
                interval=interval_seconds,
            )
            if stop_event.wait(interval_seconds):
                break
        log_event(
            logger,
            logging.INFO,
            event="service.heartbeat.stop",
            message="heartbeat logger stopping",
            service=service_name,
        )

    Thread(target=_run, name=f"{service_name}-heartbeat", daemon=True).start()
    return stop_event


def setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter(service_name))
    root.handlers = [handler]

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler]
        logger.setLevel(level)
        logger.propagate = logger_name != "uvicorn.access"
    return logging.getLogger(service_name)
