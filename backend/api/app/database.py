from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

settings = get_settings()
engine = create_engine(
    settings.database_url,
    future=True,
    echo=settings.database_echo,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def _alembic_config() -> Config:
    """Return a configured Alembic Config instance pointing at our migrations."""

    candidates = [Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]]
    migrations_root = None
    for candidate in candidates:
        maybe = candidate / "migrations"
        if maybe.exists():
            migrations_root = maybe
            break
    if migrations_root is None:
        raise RuntimeError("Unable to locate migrations directory")
    cfg = Config(str(migrations_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(migrations_root))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    cfg.attributes["configure_logger"] = False
    return cfg


def run_migrations() -> None:
    """Apply the latest database migrations."""

    command.upgrade(_alembic_config(), "head")
