from __future__ import annotations

import sys

from redis import Redis
from sqlalchemy import create_engine, text

from .config import get_settings


def _check_database(database_url: str) -> None:
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _check_redis(redis_url: str) -> None:
    client = Redis.from_url(redis_url)
    try:
        client.ping()
    finally:
        client.close()


def main() -> int:
    settings = get_settings()
    failures: list[str] = []

    try:
        _check_database(settings.database_url)
    except Exception as exc:  # pragma: no cover - defensive
        failures.append(f"database unavailable: {exc}")

    try:
        _check_redis(settings.redis_url)
    except Exception as exc:  # pragma: no cover - defensive
        failures.append(f"redis unavailable: {exc}")

    if failures:
        for failure in failures:
            print(f"[healthcheck] {failure}", file=sys.stderr)
        return 1

    print("[healthcheck] ok")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
