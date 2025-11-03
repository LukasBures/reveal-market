from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import get_settings
from app.database import get_session
from app.main import app


class InMemoryCache:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.store.keys()):
            if key.startswith(prefix):
                yield key


@pytest.fixture()
def test_database(monkeypatch, tmp_path):
    db_file = tmp_path / "api_test.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("RM_DATABASE_URL", db_url)

    get_settings.cache_clear()
    settings = get_settings()

    engine = create_engine(
        db_url,
        future=True,
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    models.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr("app.database.engine", engine, raising=False)
    monkeypatch.setattr("app.database.SessionLocal", testing_session_local, raising=False)
    monkeypatch.setattr("app.database.settings", settings, raising=False)
    monkeypatch.setattr("app.main.settings", settings, raising=False)

    def fake_run_migrations() -> None:
        models.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr("app.database.run_migrations", fake_run_migrations, raising=False)

    yield engine, testing_session_local

    models.Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if db_file.exists():
        db_file.unlink()


@pytest.fixture()
def db_session(test_database):
    _, testing_session_local = test_database
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(test_database):
    _, testing_session_local = test_database

    def override_get_session():
        db = testing_session_local()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session
    original_cache = getattr(app, "cache_client", None)
    import app.main as api_main

    original_module_cache = getattr(api_main, "cache_client", None)
    new_cache = InMemoryCache()
    app.cache_client = new_cache
    api_main.cache_client = new_cache

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
