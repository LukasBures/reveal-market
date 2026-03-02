from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from shared.migrations import run_migrations as apply_migrations
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .runtime import configure_db_metrics

settings = get_settings()
logger = logging.getLogger("reveal_market.api")
engine = create_async_engine(
    settings.resolved_async_database_url,
    future=True,
    echo=settings.database_echo,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    pool_recycle=1800,
    connect_args={
        "prepared_statement_cache_size": 256,
        "command_timeout": 30,
    },
)
configure_db_metrics(engine.sync_engine)
SessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


def run_migrations() -> None:
    """Apply the latest database migrations."""

    start_time = time.perf_counter()
    url = make_url(settings.database_url)
    logger.info(
        "running database migrations",
        extra={
            "event": "db.migrations.start",
            "database_driver": url.drivername,
            "database_host": url.host,
            "database_name": url.database,
        },
    )
    apply_migrations(settings.database_url)
    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(
        "database migrations applied",
        extra={
            "event": "db.migrations.complete",
            "database_driver": url.drivername,
            "database_host": url.host,
            "database_name": url.database,
            "duration_ms": duration_ms,
        },
    )
