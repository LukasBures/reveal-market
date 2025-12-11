from __future__ import annotations

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .config import get_settings


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return 0
    except SQLAlchemyError as exc:  # pragma: no cover - defensive
        print(f"[healthcheck] database connectivity failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
