"""Standalone healthcheck script used by container probes."""

from __future__ import annotations

import asyncio
import sys

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .cache import get_redis_client
from .config import get_settings


def _check_database(database_url: str) -> None:
    """Perform a sync DB connectivity check using SQLAlchemy text select."""

    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise RuntimeError(f"database unavailable: {exc}") from exc
    finally:
        engine.dispose()


async def _check_redis(redis_url: str) -> None:
    """Ping Redis using the shared client if available."""

    # Prefer the cached client used by the app; fall back to a fresh one only if unavailable.
    client: Redis | None = get_redis_client()
    if client is None:
        client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except RedisError as exc:
        raise RuntimeError(f"redis unavailable: {exc}") from exc


def main() -> int:
    """Return 0 when DB and Redis are reachable, otherwise print failures."""

    settings = get_settings()
    failures: list[str] = []

    try:
        _check_database(settings.database_url)
    except RuntimeError as exc:  # pragma: no cover - defensive
        failures.append(f"database unavailable: {exc}")

    try:
        asyncio.run(_check_redis(settings.redis_url))
    except RuntimeError as exc:  # pragma: no cover - defensive
        failures.append(f"redis unavailable: {exc}")

    if failures:
        for failure in failures:
            print(f"[healthcheck] {failure}", file=sys.stderr)
        return 1

    print("[healthcheck] ok")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
