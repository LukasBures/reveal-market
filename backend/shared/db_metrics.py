from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.engine import Engine


@dataclass
class DbMetricsSnapshot:
    query_count: int
    total_time_ms: float


_query_count: contextvars.ContextVar[int] = contextvars.ContextVar("db_query_count", default=0)
_query_time: contextvars.ContextVar[float] = contextvars.ContextVar("db_query_time", default=0.0)
_query_start: contextvars.ContextVar[float | None] = contextvars.ContextVar("db_query_start", default=None)


def reset_metrics() -> None:
    _query_count.set(0)
    _query_time.set(0.0)
    _query_start.set(None)


def snapshot() -> DbMetricsSnapshot:
    return DbMetricsSnapshot(query_count=_query_count.get(), total_time_ms=_query_time.get())


def _before_cursor_execute(*_args, **_kwargs) -> None:
    _query_start.set(time.perf_counter())


def _after_cursor_execute(*_args, **_kwargs) -> None:
    start = _query_start.get()
    if start is None:
        return
    elapsed_ms = (time.perf_counter() - start) * 1000
    _query_time.set(_query_time.get() + elapsed_ms)
    _query_count.set(_query_count.get() + 1)


def attach_db_metrics(engine: Engine) -> None:
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
