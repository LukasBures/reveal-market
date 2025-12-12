from __future__ import annotations

from app.config import Settings


def test_resolved_async_database_url_preserves_password():
    settings = Settings(database_url="postgresql+psycopg2://user:<REDACTED>@db:5432/reveal")

    assert settings.resolved_async_database_url == "postgresql+asyncpg://user:<REDACTED>@db:5432/reveal"


def test_resolved_async_database_url_prefers_override():
    settings = Settings(
        database_url="postgresql+psycopg2://user:<REDACTED>@db:5432/reveal",
        database_async_url="postgresql+asyncpg://user:<REDACTED>@async-db:5432/reveal_async",
    )

    assert settings.resolved_async_database_url == "postgresql+asyncpg://user:<REDACTED>@async-db:5432/reveal_async"
