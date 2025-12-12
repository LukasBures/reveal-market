from __future__ import annotations

from typing import Any

from fastapi import Request


def extract_cache_hit(request: Request | None) -> bool | None:
    ctx = getattr(request.state, "cache_context", None) if request else None
    if isinstance(ctx, dict):
        return ctx.get("cache_hit")
    return None


def extract_cache_metadata(request: Request | None) -> dict[str, Any]:
    ctx = getattr(request.state, "cache_context", None) if request else None
    if isinstance(ctx, dict):
        return {
            "cache_key": ctx.get("cache_key"),
            "cache_source": ctx.get("cache_source"),
            "cache_hit": ctx.get("cache_hit"),
        }
    return {"cache_key": None, "cache_source": None, "cache_hit": None}


def estimate_response_bytes(response) -> int:
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
