from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.fx import FxOracle
from app.types import FxQuote


@pytest.mark.asyncio
async def test_fx_oracle_refresh_and_haircut(monkeypatch):
    oracle = FxOracle(
        feed_url="http://example.com/fx",
        haircut_bps=500,
        timeout_seconds=1,
        max_age_seconds=120,
        client=None,
        retry_attempts=1,
    )

    async def _fake_fetch() -> FxQuote:
        return FxQuote(zen_usd=Decimal("0.20"), fetched_at=datetime.now(UTC))

    monkeypatch.setattr(oracle, "_fetch_quote", _fake_fetch)

    quote = await oracle.refresh()
    assert quote.zen_usd == Decimal("0.20")
    usd = oracle.usd_from_zen(Decimal("10"), quote)
    # haircut: 10 * 0.20 * 0.95 = 1.9
    assert usd == Decimal("1.90000000")


def test_fx_oracle_stale_detection():
    oracle = FxOracle(
        feed_url="http://example.com/fx",
        haircut_bps=0,
        timeout_seconds=1,
        max_age_seconds=1,
        client=None,
        retry_attempts=1,
    )
    quote = FxQuote(zen_usd=Decimal("0.21"), fetched_at=datetime.now(UTC) - timedelta(seconds=5))
    oracle._quote = quote  # type: ignore[attr-defined]
    assert oracle.stale() is True
