from __future__ import annotations

from decimal import Decimal

from app.exposure import MarketExposure


def test_register_fill_unwind_reduces_hedged():
    market = MarketExposure("m")
    market.hedged_usd = Decimal("5")
    market.register_fill(Decimal("2"), is_unwind=True)
    assert market.hedged_usd == Decimal("3")
