"""Shared test fixtures — includes Redis and PostgreSQL lifecycle management for live tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from shared.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use DB 15 to avoid clobbering dev data from ``make stack`` (which uses DB 0).
_REDIS_URL = "redis://localhost:6379/15"
_CONTAINER_NAME = "pytest-live-redis"


def _redis_is_reachable(url: str = _REDIS_URL) -> bool:
    """Synchronously check whether Redis is reachable at the given URL."""
    try:
        import redis as sync_redis

        client = sync_redis.Redis.from_url(url, socket_timeout=2.0)
        client.ping()
        client.close()
    except Exception:
        return False
    return True


def _start_redis_container() -> bool:
    """Start a disposable Redis 7 container; return True on success."""
    if shutil.which("docker") is None:
        return False
    # Remove stale container if it exists.
    _rm_cmd = ["docker", "rm", "-f", _CONTAINER_NAME]  # noqa: S607
    subprocess.run(_rm_cmd, capture_output=True)  # noqa: S603
    _run_cmd = [  # noqa: S607
        "docker",
        "run",
        "-d",
        "--name",
        _CONTAINER_NAME,
        "-p",
        "6379:6379",
        "redis:7-alpine",
        "redis-server",
        "--save",
        "",
        "--appendonly",
        "no",
    ]
    result = subprocess.run(_run_cmd, capture_output=True)  # noqa: S603
    if result.returncode != 0:
        return False
    # Wait for Redis to be ready (up to 10 seconds).
    for _ in range(20):
        if _redis_is_reachable():
            return True
        time.sleep(0.5)
    return False


def _stop_redis_container() -> None:
    _cmd = ["docker", "rm", "-f", _CONTAINER_NAME]  # noqa: S607
    subprocess.run(_cmd, capture_output=True)  # noqa: S603


@pytest.fixture(scope="session")
def _redis_server():
    """Ensure a Redis server is available for the entire test session."""
    owned = False
    if not _redis_is_reachable():
        if not _start_redis_container():
            pytest.skip("Redis not available and could not start Docker container")
        owned = True
    yield
    if owned:
        _stop_redis_container()


@pytest.fixture()
async def redis_client(_redis_server):
    """Return an async Redis client connected to the test DB, flushed before each test.

    Uses ``cache_async.get_client()`` so we exercise the actual client factory
    (pool size, socket timeouts, health_check_interval, etc.).
    """
    from shared.cache_async import get_client

    client = get_client(_REDIS_URL)
    if client is None:
        pytest.skip("Failed to create Redis client")
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture()
async def raw_redis_client(_redis_server):
    """Return a Redis client with ``decode_responses=False`` for inspecting raw bytes.

    This is needed to check compression markers (``zl:`` prefix) that are
    invisible through the decode-responses client used by production code.
    """
    client = Redis.from_url(_REDIS_URL, decode_responses=False)
    await client.flushdb()
    yield client
    await client.aclose()


# ────────────────────────────────────────────────────────────────
# PostgreSQL test fixtures (live integration tests)
# ────────────────────────────────────────────────────────────────

_PG_PORT = int(os.getenv("TEST_PG_PORT", "15432"))
_PG_USER = "test_admin"
_PG_PASS = "test_admin"  # noqa: S105
_PG_DB = "reveal_market_test"
_PG_URL = f"postgresql+asyncpg://{_PG_USER}:<REDACTED>@localhost:{_PG_PORT}/{_PG_DB}"
_PG_CONTAINER_NAME = "reveal-market-test-pg"


def _pg_is_reachable() -> bool:
    """Check whether PostgreSQL is reachable on the test port."""
    try:
        _pg_ready_cmd = ["docker", "exec", _PG_CONTAINER_NAME, "pg_isready", "-U", _PG_USER, "-d", _PG_DB]  # noqa: S607
        result = subprocess.run(_pg_ready_cmd, capture_output=True, timeout=5)  # noqa: S603
        return result.returncode == 0
    except Exception:
        return False


def _start_pg_container() -> bool:
    """Start a disposable PostgreSQL 15 container; return True on success."""
    if shutil.which("docker") is None:
        return False
    _rm_pg_cmd = ["docker", "rm", "-f", _PG_CONTAINER_NAME]  # noqa: S607
    subprocess.run(_rm_pg_cmd, capture_output=True)  # noqa: S603
    _run_pg_cmd = [  # noqa: S607
        "docker",
        "run",
        "-d",
        "--name",
        _PG_CONTAINER_NAME,
        "-e",
        f"POSTGRES_USER={_PG_USER}",
        "-e",
        f"POSTGRES_PASSWORD={_PG_PASS}",
        "-e",
        f"POSTGRES_DB={_PG_DB}",
        "-p",
        f"{_PG_PORT}:5432",
        "postgres:15-alpine",
        "-c",
        "shared_preload_libraries=pg_stat_statements",
        "-c",
        "jit=off",
    ]
    result = subprocess.run(_run_pg_cmd, capture_output=True)  # noqa: S603
    if result.returncode != 0:
        return False
    for _ in range(30):
        if _pg_is_reachable():
            # Also create the pg_stat_statements extension.
            _ext_cmd = [  # noqa: S607
                "docker",
                "exec",
                _PG_CONTAINER_NAME,
                "psql",
                "-U",
                _PG_USER,
                "-d",
                _PG_DB,
                "-c",
                "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;",
            ]
            subprocess.run(_ext_cmd, capture_output=True)  # noqa: S603
            return True
        time.sleep(1)
    return False


def _stop_pg_container() -> None:
    subprocess.run(["docker", "rm", "-f", _PG_CONTAINER_NAME], capture_output=True)  # noqa: S603, S607


@pytest.fixture(scope="session")
def _pg_server():
    """Ensure a PostgreSQL server is available for the entire test session."""
    owned = False
    if not _pg_is_reachable():
        if not _start_pg_container():
            pytest.skip("PostgreSQL not available and could not start Docker container")
        owned = True
    yield
    if owned:
        _stop_pg_container()


@pytest_asyncio.fixture
async def pg_engine(_pg_server):
    """Per-test async engine connected to the test PostgreSQL.

    Function-scoped to avoid event-loop mismatch: pytest-asyncio creates a new
    event loop per test, so session-scoped async engines break on the 2nd test.
    """
    engine = create_async_engine(_PG_URL, future=True, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncSession:  # type: ignore[misc]
    """Per-test async session with full schema created, then dropped after test."""
    from sqlalchemy import text as sa_text

    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add PostgreSQL-specific stored tsvector column + GIN index.
        # This can't live in the SQLAlchemy model because tsvector/GENERATED ALWAYS
        # would break the SQLite-based unit tests.
        await conn.execute(
            sa_text(
                "ALTER TABLE markets ADD COLUMN IF NOT EXISTS search_vector tsvector"
                " GENERATED ALWAYS AS ("
                "   to_tsvector('english',"
                "     coalesce(title, '') || ' ' || coalesce(slug, '') || ' ' ||"
                "     coalesce(event_key, '') || ' ' || coalesce(category, '')"
                "   )"
                " ) STORED"
            )
        )
        await conn.execute(
            sa_text("CREATE INDEX IF NOT EXISTS ix_markets_search_vector ON markets USING gin(search_vector)")
        )

    session_factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
