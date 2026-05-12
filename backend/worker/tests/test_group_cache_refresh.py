import pytest

from app import service


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_calls = 0

    async def rollback(self) -> None:
        self.rollback_calls += 1


@pytest.mark.asyncio
async def test_group_cache_refresh_failure_is_best_effort(monkeypatch):
    async def _raise_timeout(*_args, **_kwargs):
        raise TimeoutError("cache query timed out")

    session = _FakeSession()
    monkeypatch.setattr(service.runtime.settings, "group_markets_cache_refresh_limit", 10)
    monkeypatch.setattr(service, "persist_group_markets_cache", _raise_timeout)

    written = await service._persist_group_markets_cache_best_effort(
        session,
        object(),
        {"group-a"},
        300,
        context="test",
    )

    assert written == 0
    assert session.rollback_calls == 1


@pytest.mark.asyncio
async def test_group_cache_refresh_success_returns_written_count(monkeypatch):
    async def _write(*_args, **_kwargs):
        return 2

    session = _FakeSession()
    monkeypatch.setattr(service.runtime.settings, "group_markets_cache_refresh_limit", 10)
    monkeypatch.setattr(service, "persist_group_markets_cache", _write)

    written = await service._persist_group_markets_cache_best_effort(
        session,
        object(),
        {"group-a", "group-b"},
        300,
        context="test",
    )

    assert written == 2
    assert session.rollback_calls == 0


@pytest.mark.asyncio
async def test_group_cache_refresh_disabled_skips_eager_write(monkeypatch):
    async def _unexpected_write(*_args, **_kwargs):
        raise AssertionError("group cache refresh should be skipped")

    session = _FakeSession()
    monkeypatch.setattr(service.runtime.settings, "group_markets_cache_refresh_limit", 0)
    monkeypatch.setattr(service, "persist_group_markets_cache", _unexpected_write)

    written = await service._persist_group_markets_cache_best_effort(
        session,
        object(),
        {"group-a"},
        300,
        context="test",
    )

    assert written == 0
    assert session.rollback_calls == 0
