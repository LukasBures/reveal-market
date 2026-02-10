"""Lightweight profiling endpoints guarded by the internal API secret."""

from __future__ import annotations

import io
from contextlib import contextmanager

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import PlainTextResponse

from app.runtime import settings

router = APIRouter(tags=["debug"])


def _verify_internal_secret(secret_header: str | None) -> None:
    secret = settings.internal_api_secret.get_secret_value() if settings.internal_api_secret else None
    if not secret or secret_header != secret:
        raise HTTPException(status_code=401, detail="invalid_internal_secret")


@contextmanager
def _profile_context(enabled: bool):
    if not enabled:
        yield None
        return
    import cProfile

    profiler = cProfile.Profile()
    profiler.enable()
    try:
        yield profiler
    finally:
        profiler.disable()


@router.get("/internal/profile", response_class=PlainTextResponse)
async def profile_request(
    seconds: float = 2.0,
    internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
):
    _verify_internal_secret(internal_secret)
    if not settings.profiling_enabled:
        raise HTTPException(status_code=403, detail="profiling_disabled")
    if seconds <= 0:
        raise HTTPException(status_code=400, detail="seconds must be positive")
    import asyncio
    import pstats

    with _profile_context(True) as profiler:
        await asyncio.sleep(seconds)
    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer).sort_stats("cumtime")
    stats.print_stats(40)
    return buffer.getvalue()
