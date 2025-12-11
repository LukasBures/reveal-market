from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from shared.migrations import run_migrations as apply_migrations
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()
engine = create_async_engine(
    settings.resolved_async_database_url,
    future=True,
    echo=settings.database_echo,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
)
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

    apply_migrations(settings.database_url)
