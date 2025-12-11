from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app import models
from app.config import get_settings
from app.database import get_session
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker


class InMemoryCache:
    def __init__(self):
        self.store: dict[str, Any] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: Any, ex: int | None = None, nx: bool | None = None):
        if nx:
            if key in self.store:
                return False
        self.store[key] = value
        return True

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key

    def sadd(self, key: str, value: str) -> None:
        self.store.setdefault(key, set()).add(value)

    def smembers(self, key: str):
        members = self.store.get(key)
        if isinstance(members, set):
            return set(members)
        return set()


@pytest.fixture()
def test_database(monkeypatch, tmp_path):
    db_file = tmp_path / "api_test.db"
    db_url = f"sqlite:///{db_file}"
    db_url_async = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("RM_DATABASE_URL", db_url)
    monkeypatch.setenv("RM_DATABASE_ASYNC_URL", db_url_async)

    get_settings.cache_clear()
    settings = get_settings()

    sync_engine = create_engine(db_url, future=True, connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(
        bind=sync_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
    )
    async_engine = create_async_engine(db_url_async, future=True, connect_args={"check_same_thread": False})
    testing_async_session = async_sessionmaker(
        bind=async_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    monkeypatch.setattr("app.database.engine", async_engine, raising=False)
    monkeypatch.setattr("app.database.SessionLocal", testing_async_session, raising=False)
    monkeypatch.setattr("app.database.settings", settings, raising=False)
    monkeypatch.setattr("app.main.settings", settings, raising=False)

    def fake_run_migrations() -> None:
        models.Base.metadata.create_all(bind=sync_engine)

    monkeypatch.setattr("app.database.run_migrations", fake_run_migrations, raising=False)
    monkeypatch.setattr("app.main.run_migrations", fake_run_migrations, raising=False)

    models.Base.metadata.create_all(bind=sync_engine)

    yield async_engine, testing_async_session, testing_session_local

    models.Base.metadata.drop_all(bind=sync_engine)
    sync_engine.dispose()
    asyncio.run(async_engine.dispose())
    if db_file.exists():
        db_file.unlink()


@pytest.fixture()
def db_session(test_database):
    _, _, testing_session_local = test_database
    session: Session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(test_database):
    _, testing_async_session, _ = test_database

    async def override_get_session():
        async with testing_async_session() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session
    original_cache = getattr(app, "cache_client", None)
    import app.main as api_main

    original_module_cache = getattr(api_main, "cache_client", None)
    new_cache = InMemoryCache()
    app.cache_client = new_cache
    api_main.cache_client = new_cache
    api_main._cache_refresh_task = None
    api_main._quote_sweeper_task = None
    api_main._metrics_task = None
    api_main.instrumentator = api_main.instrumentator  # ensure metrics setup stays bound
    if hasattr(api_main, "_resolution_client"):
        api_main._resolution_client = None

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if original_cache is not None:
            app.cache_client = original_cache
        elif hasattr(app, "cache_client"):
            delattr(app, "cache_client")
        api_main.cache_client = original_module_cache
        app.dependency_overrides.pop(get_session, None)
