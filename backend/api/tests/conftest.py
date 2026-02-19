from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

# Ensure required env vars exist before importing runtime/settings in test modules.
os.environ.setdefault("PROVER_CIRCUIT_HASH", "0x" + "deadbeef" * 8)
os.environ.setdefault("RM_PRICING_SIGNER_PRIVATE_KEY", "0x" + "1" * 64)


class InMemoryCache:
    def __init__(self):
        self.store: dict[str, Any] = {}

    async def ping(self) -> bool:  # pragma: no cover - trivial
        return True

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool | None = None):
        if nx:
            if key in self.store:
                return False
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    async def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key

    async def sscan_iter(self, key: str, count: int | None = None):
        members = self.store.get(key)
        if isinstance(members, set):
            for member in members:
                yield member

    async def sadd(self, key: str, value: str) -> None:
        self.store.setdefault(key, set()).add(value)

    async def smembers(self, key: str):
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
    monkeypatch.setenv(
        "PROVER_CIRCUIT_HASH",
        "0x" + "deadbeef" * 8,
    )
    # Mirror required signer envs to satisfy pricing/quote initialization in tests.
    monkeypatch.setenv("RM_PRICING_SIGNER_PRIVATE_KEY", "0x" + "1" * 64)

    from app import models, runtime
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    for key, value in settings.model_dump().items():
        setattr(runtime.settings, key, value)
    settings = runtime.settings

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

    monkeypatch.setattr("app.runtime.settings", settings, raising=False)
    monkeypatch.setattr("app.database.engine", async_engine, raising=False)
    monkeypatch.setattr("app.database.SessionLocal", testing_async_session, raising=False)
    monkeypatch.setattr("app.database.settings", settings, raising=False)
    monkeypatch.setattr("app.server.settings", settings, raising=False)
    monkeypatch.setattr("app.tasks.settings", settings, raising=False)

    def fake_run_migrations() -> None:
        models.Base.metadata.create_all(bind=sync_engine)

    monkeypatch.setattr("app.database.run_migrations", fake_run_migrations, raising=False)
    monkeypatch.setattr("app.tasks.run_migrations", fake_run_migrations, raising=False)

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
def client(test_database, monkeypatch):
    _, testing_async_session, _ = test_database

    async def override_get_session():
        async with testing_async_session() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    import app.runtime as runtime
    import app.server as api_main
    from app.database import get_session

    app = api_main.app
    app.dependency_overrides[get_session] = override_get_session
    original_cache = getattr(app, "cache_client", None)

    original_module_cache = getattr(api_main, "cache_client", None)
    original_runtime_cache = getattr(runtime, "cache_client", None)
    new_cache = InMemoryCache()
    app.cache_client = new_cache
    api_main.cache_client = new_cache
    runtime.cache_client = new_cache
    app.state.cache_client = new_cache  # type: ignore[attr-defined]

    async def _noop_startup():
        return None

    async def _noop_stop():
        return None

    monkeypatch.setattr("app.server.run_startup_tasks", _noop_startup, raising=False)
    monkeypatch.setattr("app.tasks.run_startup_tasks", _noop_startup, raising=False)
    monkeypatch.setattr("app.server.stop_background_tasks", _noop_stop, raising=False)
    monkeypatch.setattr("app.tasks.stop_background_tasks", _noop_stop, raising=False)
    if hasattr(api_main, "cache_refresh_task"):
        api_main.cache_refresh_task = None
    if hasattr(api_main, "quote_sweeper_task"):
        api_main.quote_sweeper_task = None
    if hasattr(api_main, "metrics_task"):
        api_main.metrics_task = None

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if original_cache is not None:
            app.cache_client = original_cache
        elif hasattr(app, "cache_client"):
            delattr(app, "cache_client")
        api_main.cache_client = original_module_cache
        runtime.cache_client = original_runtime_cache
        app.dependency_overrides.pop(get_session, None)
