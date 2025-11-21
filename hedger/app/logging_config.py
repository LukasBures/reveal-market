from __future__ import annotations

import logging

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


def setup_logging(service_name: str, level: str = "INFO") -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter(service_name))
    handler.addFilter(RequestContextFilter(service_name))
    root.handlers = [handler]

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = [handler]
        logger.setLevel(level)
        logger.propagate = logger_name != "uvicorn.access"
    # Quiet overly chatty dependencies.
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    return logging.getLogger(service_name)
