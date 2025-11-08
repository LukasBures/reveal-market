from __future__ import annotations

import logging
from contextvars import ContextVar, Token

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
    """Emit a structured log with a consistent event field."""

    extra = {"event": event}
    extra.update(fields)
    logger.log(level, message, extra=extra)
