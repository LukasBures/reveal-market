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
    max_time_ms: float


@dataclass(frozen=True)
class DbQueryHotspot:
    query: str
    query_count: int
    total_time_ms: float
    max_time_ms: float

    @property
    def avg_time_ms(self) -> float:
        if self.query_count <= 0:
            return 0.0
        return self.total_time_ms / self.query_count


_query_count: contextvars.ContextVar[int] = contextvars.ContextVar("db_query_count", default=0)
_query_time: contextvars.ContextVar[float] = contextvars.ContextVar("db_query_time", default=0.0)
_query_start: contextvars.ContextVar[float | None] = contextvars.ContextVar("db_query_start", default=None)
_query_statement: contextvars.ContextVar[str | None] = contextvars.ContextVar("db_query_statement", default=None)
_query_max: contextvars.ContextVar[float] = contextvars.ContextVar("db_query_max", default=0.0)
_query_hotspots: contextvars.ContextVar[dict[str, tuple[int, float, float]] | None] = contextvars.ContextVar(
    "db_query_hotspots",
    default=None,
)


def reset_metrics() -> None:
    _query_count.set(0)
    _query_time.set(0.0)
    _query_start.set(None)
    _query_statement.set(None)
    _query_max.set(0.0)
    _query_hotspots.set(None)


def snapshot() -> DbMetricsSnapshot:
    return DbMetricsSnapshot(
        query_count=_query_count.get(),
        total_time_ms=_query_time.get(),
        max_time_ms=_query_max.get(),
    )


def snapshot_hotspots(*, limit: int = 5, min_total_time_ms: float = 0.0) -> list[DbQueryHotspot]:
    if limit <= 0:
        return []
    raw = _query_hotspots.get() or {}
    hotspots: list[DbQueryHotspot] = []
    for query, (query_count, total_time_ms, max_time_ms) in raw.items():
        if total_time_ms < min_total_time_ms:
            continue
        hotspots.append(
            DbQueryHotspot(
                query=query,
                query_count=query_count,
                total_time_ms=total_time_ms,
                max_time_ms=max_time_ms,
            )
        )
    hotspots.sort(key=lambda item: (item.total_time_ms, item.query_count, item.max_time_ms), reverse=True)
    return hotspots[:limit]


def _normalize_statement(statement: str, *, max_length: int = 240) -> str:
    collapsed = " ".join(statement.split())
    if not collapsed:
        return "<empty>"
    if len(collapsed) <= max_length:
        return collapsed
    return f"{collapsed[: max_length - 3]}..."


def _before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
    _query_start.set(time.perf_counter())
    if isinstance(statement, str):
        _query_statement.set(_normalize_statement(statement))
    else:
        _query_statement.set("<non-sql>")


def _after_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
    start = _query_start.get()
    if start is None:
        _query_statement.set(None)
        return
    elapsed_ms = (time.perf_counter() - start) * 1000
    _query_time.set(_query_time.get() + elapsed_ms)
    _query_count.set(_query_count.get() + 1)
    if elapsed_ms > _query_max.get():
        _query_max.set(elapsed_ms)
    statement_key = _query_statement.get()
    if not statement_key:
        statement_key = _normalize_statement(statement) if isinstance(statement, str) else "<non-sql>"
    hotspots = dict(_query_hotspots.get() or {})
    query_count, total_time_ms, max_time_ms = hotspots.get(statement_key, (0, 0.0, 0.0))
    hotspots[statement_key] = (query_count + 1, total_time_ms + elapsed_ms, max(max_time_ms, elapsed_ms))
    _query_hotspots.set(hotspots)
    _query_statement.set(None)


def attach_db_metrics(engine: Engine) -> None:
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
