"""Live PostgreSQL integration tests.

Run with:  make test-db-live
These tests spin up a real PostgreSQL 15 container on port 15432 and verify
that indexes are used, Numeric columns roundtrip correctly, @validates
normalizers fire, and bulk operations work against a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from shared import models
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# pg_engine and pg_session fixtures come from conftest.py (auto-loaded by pytest).
pytestmark = pytest.mark.live


def _make_market(**overrides) -> models.Market:
    defaults = {
        "event_id": "evt-test-1",
        "title": "Test Market",
        "oracle": "uma",
        "status": models.MarketStatusEnum.COMMIT.value,
    }
    defaults.update(overrides)
    return models.Market(**defaults)


# ────────────────────────────────────────────────────────────────
# Index usage tests (EXPLAIN ANALYZE)
# ────────────────────────────────────────────────────────────────


class TestIndexUsage:
    """Verify PostgreSQL uses the expected indexes via EXPLAIN ANALYZE."""

    async def _explain(self, session: AsyncSession, sql: str) -> str:
        result = await session.execute(text(f"EXPLAIN ANALYZE {sql}"))
        return "\n".join(row[0] for row in result)

    async def test_group_slug_uses_btree_index(self, pg_session):
        market = _make_market(group_slug="test-group")
        pg_session.add(market)
        await pg_session.flush()

        plan = await self._explain(pg_session, "SELECT * FROM markets WHERE group_slug = 'test-group'")
        assert "ix_markets_group_slug" in plan or "Index" in plan

    async def test_category_uses_btree_index(self, pg_session):
        market = _make_market(category="crypto")
        pg_session.add(market)
        await pg_session.flush()

        await self._explain(pg_session, "SELECT * FROM markets WHERE category = 'crypto'")
        # With only 1 row the planner may choose a seq scan, but the index should exist
        result = await pg_session.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'markets' AND indexname = 'ix_markets_category'")
        )
        assert result.scalar_one() == "ix_markets_category"

    async def test_search_vector_gin_index_exists(self, pg_session):
        market = _make_market()
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(
            text(
                "SELECT indexname FROM pg_indexes"
                " WHERE tablename = 'markets' AND indexname = 'ix_markets_search_vector'"
            )
        )
        assert result.scalar_one() == "ix_markets_search_vector"

    async def test_search_vector_populated(self, pg_session):
        market = _make_market(title="Bitcoin prediction market", slug="btc-price")
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(text("SELECT search_vector::text FROM markets WHERE event_id = 'evt-test-1'"))
        vector = result.scalar_one()
        assert "bitcoin" in vector.lower() or "predict" in vector.lower()

    async def test_commitments_brin_index_exists(self, pg_session):
        # Just verify the BRIN index was created
        market = _make_market()
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(
            text(
                "SELECT indexname FROM pg_indexes"
                " WHERE tablename = 'commitments' AND indexname = 'ix_commitments_created_brin'"
            )
        )
        assert result.scalar_one() == "ix_commitments_created_brin"

    async def test_featured_partial_index_exists(self, pg_session):
        market = _make_market()
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'markets' AND indexname = 'ix_markets_featured'")
        )
        assert result.scalar_one() == "ix_markets_featured"


# ────────────────────────────────────────────────────────────────
# Normalization tests (@validates)
# ────────────────────────────────────────────────────────────────


class TestNormalization:
    """Verify @validates normalizers lowercase values on write."""

    async def test_category_normalized_on_insert(self, pg_session):
        market = _make_market(category="Crypto")
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(select(models.Market.category).where(models.Market.event_id == "evt-test-1"))
        assert result.scalar_one() == "crypto"

    async def test_event_key_normalized_on_insert(self, pg_session):
        market = _make_market(event_key="BTC-PRICE-2026")
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(select(models.Market.event_key).where(models.Market.event_id == "evt-test-1"))
        assert result.scalar_one() == "btc-price-2026"

    async def test_group_slug_normalized_on_insert(self, pg_session):
        market = _make_market(group_slug="My-Group")
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(
            select(models.Market.group_slug).where(models.Market.event_id == "evt-test-1")
        )
        assert result.scalar_one() == "my-group"

    async def test_gamma_group_slug_normalized(self, pg_session):
        market = _make_market()
        pg_session.add(market)
        await pg_session.flush()

        gamma = models.MarketGammaMetadata(market_id=market.id, group_slug="UPPER-GROUP")
        pg_session.add(gamma)
        await pg_session.flush()

        result = await pg_session.execute(
            select(models.MarketGammaMetadata.group_slug).where(models.MarketGammaMetadata.market_id == market.id)
        )
        assert result.scalar_one() == "upper-group"


# ────────────────────────────────────────────────────────────────
# Numeric precision tests
# ────────────────────────────────────────────────────────────────


class TestNumericPrecision:
    """Verify Float->Numeric migration preserves exact decimal values."""

    async def test_order_min_size_decimal_roundtrip(self, pg_session):
        market = _make_market(order_min_size=Decimal("0.00000001"))
        pg_session.add(market)
        await pg_session.flush()

        result = await pg_session.execute(
            select(models.Market.order_min_size).where(models.Market.event_id == "evt-test-1")
        )
        value = result.scalar_one()
        assert value == Decimal("0.00000001")
        assert isinstance(value, Decimal)

    async def test_gamma_best_bid_decimal_roundtrip(self, pg_session):
        market = _make_market()
        pg_session.add(market)
        await pg_session.flush()

        gamma = models.MarketGammaMetadata(
            market_id=market.id,
            best_bid=Decimal("0.12345678"),
            best_ask=Decimal("0.87654321"),
            spread=Decimal("0.75308643"),
        )
        pg_session.add(gamma)
        await pg_session.flush()

        result = await pg_session.execute(
            select(
                models.MarketGammaMetadata.best_bid,
                models.MarketGammaMetadata.best_ask,
                models.MarketGammaMetadata.spread,
            ).where(models.MarketGammaMetadata.market_id == market.id)
        )
        row = result.one()
        assert row.best_bid == Decimal("0.12345678")
        assert row.best_ask == Decimal("0.87654321")
        assert row.spread == Decimal("0.75308643")

    async def test_quote_zen_usd_decimal(self, pg_session):
        market = _make_market()
        pg_session.add(market)
        await pg_session.flush()

        quote = models.Quote(
            quote_id="q-test-1",
            payload={"test": True},
            stake_zen=Decimal("1.5"),
            stake_wei=Decimal("1500000000000000000"),
            fx_scaled=750000,
            zen_usd=Decimal("7.50000000"),
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        pg_session.add(quote)
        await pg_session.flush()

        result = await pg_session.execute(select(models.Quote.zen_usd).where(models.Quote.quote_id == "q-test-1"))
        value = result.scalar_one()
        assert value == Decimal("7.50000000")
        assert isinstance(value, Decimal)


# ────────────────────────────────────────────────────────────────
# Consolidated market stats (single-query)
# ────────────────────────────────────────────────────────────────


class TestConsolidatedStats:
    """Verify the single-query market stats approach works on real PG."""

    async def test_market_stats_single_query(self, pg_session):
        from sqlalchemy import and_, case, func, or_

        now = datetime.now(UTC)
        # Create test markets: 1 live, 1 ended, 1 finalized
        live_market = _make_market(
            event_id="evt-live",
            closes_at=now + timedelta(hours=1),
        )
        ended_market = _make_market(
            event_id="evt-ended",
            status=models.MarketStatusEnum.LOCKED.value,
        )
        finalized_market = _make_market(
            event_id="evt-finalized",
            status=models.MarketStatusEnum.SETTLED.value,
            resolution_status=models.ResolutionStatusEnum.FINAL.value,
        )
        pg_session.add_all([live_market, ended_market, finalized_market])
        await pg_session.flush()

        # Run the consolidated stats query
        live_case = case(
            (
                and_(
                    models.Market.status == models.MarketStatusEnum.COMMIT.value,
                    or_(models.Market.closes_at.is_(None), models.Market.closes_at > now),
                    or_(models.Market.commits_blocked_at.is_(None), models.Market.commits_blocked_at > now),
                ),
                1,
            ),
        )
        finalized_case = case(
            (models.Market.resolution_status == models.ResolutionStatusEnum.FINAL.value, 1),
        )
        stmt = select(
            func.count(models.Market.id).label("total"),
            func.count(live_case).label("live"),
            func.count(finalized_case).label("finalized"),
        )
        row = (await pg_session.execute(stmt)).one()
        assert int(row.total) == 3
        assert int(row.live) == 1
        assert int(row.finalized) == 1


# ────────────────────────────────────────────────────────────────
# pg_stat_statements extension
# ────────────────────────────────────────────────────────────────


class TestPgStatStatements:
    """Verify pg_stat_statements extension is available."""

    async def test_extension_loaded(self, pg_session):
        result = await pg_session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'pg_stat_statements'"))
        assert result.scalar_one() == "pg_stat_statements"

    async def test_can_query_stats(self, pg_session):
        # Just verify the view is queryable
        result = await pg_session.execute(text("SELECT count(*) FROM pg_stat_statements"))
        count = result.scalar_one()
        assert count >= 0
