from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from shared.db_metrics import attach_db_metrics
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()
engine = create_async_engine(
    settings.resolved_async_database_url,
    future=True,
    # Disable SQL echo to keep container logs concise; structured events are emitted separately.
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
)
attach_db_metrics(engine.sync_engine)
SessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope around a series of DB operations."""

    session = SessionLocal()
    try:
        yield session
        if session.in_transaction():
            await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
