from __future__ import annotations

from typing import Any

from fastapi import Request


def extract_cache_hit(request: Request | None) -> bool | None:
    state = getattr(request, "state", None) if request is not None else None
    ctx = getattr(state, "cache_context", None) if state is not None else None
    if isinstance(ctx, dict):
        return ctx.get("cache_hit")
    return None


def extract_cache_metadata(request: Request | None) -> dict[str, Any]:
    state = getattr(request, "state", None) if request is not None else None
    ctx = getattr(state, "cache_context", None) if state is not None else None
    if isinstance(ctx, dict):
        return {
            "cache_key": ctx.get("cache_key"),
            "cache_source": ctx.get("cache_source"),
            "cache_hit": ctx.get("cache_hit"),
        }
    return {"cache_key": None, "cache_source": None, "cache_hit": None}


def estimate_response_bytes(response) -> int:
    """
    Estimate the size of an HTTP response body in bytes.

    The `response` object is expected to expose a `headers` mapping with a `get`
    method (for example, a FastAPI/Starlette Response) and may optionally
    provide a `body` attribute containing the raw payload as `bytes` or
    `bytearray`. The function first attempts to read and parse the
    `Content-Length` header. If it is present and can be converted to an
    integer, that value is returned. Otherwise, if a bytes-like `body` attribute
    is available, its length is returned. If neither of these sources is usable,
    `0` is returned.

    :param response: Response object with a headers mapping and optional
        bytes-like `body` attribute.
    :return: Estimated response size in bytes, or `0` if it cannot be
        determined.
    """
    header_len = response.headers.get("content-length")
    if header_len:
        try:
            return int(header_len)
        except ValueError:
            pass
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return len(body)
    return 0
