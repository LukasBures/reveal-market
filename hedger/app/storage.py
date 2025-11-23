from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .types import CommitEvent, HedgeInstruction

Base = declarative_base()


class CommitRecord(Base):
    __tablename__ = "hedger_commits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String, nullable=False, index=True)
    direction = Column(String, nullable=False)
    stake_zen = Column(Numeric(precision=32, scale=8), nullable=False)
    stake_usd = Column(Numeric(precision=32, scale=8), nullable=False)
    committed_at = Column(DateTime(timezone=True), nullable=False)
    tx_hash = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True, index=True)
    account = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    metadata_source = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class HedgeActionRecord(Base):
    __tablename__ = "hedger_hedge_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String, nullable=False, index=True)
    hedge_outcome = Column(String, nullable=False)
    action = Column(String, nullable=False)
    size_usd = Column(Numeric(precision=32, scale=8), nullable=False)
    slippage_bps = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    target_coverage = Column(Numeric(precision=10, scale=4), nullable=False)
    status = Column(String, nullable=False, default="planned")
    response_payload = Column(JSON, nullable=True)
    is_unwind = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class SettlementRecord(Base):
    __tablename__ = "hedger_settlements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False)
    proof_payload = Column(JSON, nullable=True)
    prover_latency_seconds = Column(Integer, nullable=True)
    submitted_tx = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class HedgerReplayOffset(Base):
    __tablename__ = "hedger_offsets"

    stream_name = Column(String, primary_key=True)
    offset = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class ResolvedMarketRecord(Base):
    __tablename__ = "hedger_resolved_markets"

    market_id = Column(String, primary_key=True)
    outcome = Column(String, nullable=False)
    resolved_at = Column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class TreasurySnapshotRecord(Base):
    __tablename__ = "hedger_treasury_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False)
    stake_zen = Column(Numeric(precision=32, scale=8), nullable=False)
    refund_zen = Column(Numeric(precision=32, scale=8), nullable=False)
    rake_zen = Column(Numeric(precision=32, scale=8), nullable=False)
    payout_profit_usdc = Column(Numeric(precision=32, scale=8), nullable=False)
    borrowed_usdc = Column(Numeric(precision=32, scale=8), nullable=False)
    lp_share_usdc = Column(Numeric(precision=32, scale=8), nullable=False)
    repay_amount_usdc = Column(Numeric(precision=32, scale=8), nullable=False)
    platform_usdc_revenue = Column(Numeric(precision=32, scale=8), nullable=False)
    zen_balance = Column(Numeric(precision=32, scale=8), nullable=False)
    usdc_balance = Column(Numeric(precision=32, scale=8), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class HedgerRepository:
    """Lightweight Postgres repository used for audit logs and crash recovery."""

    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine, checkfirst=True)

    def check_connection(self) -> None:
        with self.SessionLocal() as session:
            session.execute(select(1))

    async def record_commit(self, commit: CommitEvent, stake_usd: Decimal, idempotency_key: str | None = None) -> None:
        await asyncio.to_thread(self._record_commit_sync, commit, stake_usd, idempotency_key)

    def _record_commit_sync(self, commit: CommitEvent, stake_usd: Decimal, idempotency_key: str | None) -> None:
        with self.SessionLocal() as session:
            row = CommitRecord(
                market_id=commit.market_id,
                direction=commit.direction,
                stake_zen=commit.stake_zen,
                stake_usd=stake_usd,
                committed_at=commit.committed_at,
                tx_hash=commit.tx_hash,
                idempotency_key=idempotency_key or commit.idempotency_key,
                account=commit.account,
                request_id=commit.request_id,
                metadata_source=commit.metadata_source,
            )
            session.add(row)
            session.commit()

    async def record_hedge_instruction(
        self, instruction: HedgeInstruction, response_payload: dict | None = None
    ) -> None:
        await asyncio.to_thread(self._record_hedge_sync, instruction, response_payload)

    def _record_hedge_sync(self, instruction: HedgeInstruction, response_payload: dict | None) -> None:
        with self.SessionLocal() as session:
            row = HedgeActionRecord(
                market_id=instruction.market_id,
                hedge_outcome=instruction.hedge_outcome,
                action=instruction.action,
                size_usd=instruction.size_usd,
                slippage_bps=instruction.slippage_bps,
                reason=instruction.reason,
                target_coverage=instruction.target_coverage,
                response_payload=response_payload,
                is_unwind=1 if instruction.is_unwind else 0,
            )
            session.add(row)
            session.commit()

    async def record_settlement(
        self,
        *,
        market_id: str,
        outcome: str,
        proof_payload: dict | None,
        prover_latency_seconds: int | None,
        submitted_tx: str | None,
    ) -> None:
        await asyncio.to_thread(
            self._record_settlement_sync,
            market_id,
            outcome,
            proof_payload,
            prover_latency_seconds,
            submitted_tx,
        )

    def _record_settlement_sync(
        self,
        market_id: str,
        outcome: str,
        proof_payload: dict | None,
        prover_latency_seconds: int | None,
        submitted_tx: str | None,
    ) -> None:
        with self.SessionLocal() as session:
            row = SettlementRecord(
                market_id=market_id,
                outcome=outcome,
                proof_payload=proof_payload,
                prover_latency_seconds=prover_latency_seconds,
                submitted_tx=submitted_tx,
            )
            session.add(row)
            session.commit()

    async def record_treasury_snapshot(
        self,
        *,
        market_id: str,
        outcome: str,
        stake_zen: Decimal,
        refund_zen: Decimal,
        rake_zen: Decimal,
        payout_profit_usdc: Decimal,
        borrowed_usdc: Decimal,
        lp_share_usdc: Decimal,
        repay_amount_usdc: Decimal,
        platform_usdc_revenue: Decimal,
        zen_balance: Decimal,
        usdc_balance: Decimal,
    ) -> None:
        await asyncio.to_thread(
            self._record_treasury_snapshot_sync,
            market_id,
            outcome,
            stake_zen,
            refund_zen,
            rake_zen,
            payout_profit_usdc,
            borrowed_usdc,
            lp_share_usdc,
            repay_amount_usdc,
            platform_usdc_revenue,
            zen_balance,
            usdc_balance,
        )

    def _record_treasury_snapshot_sync(
        self,
        market_id: str,
        outcome: str,
        stake_zen: Decimal,
        refund_zen: Decimal,
        rake_zen: Decimal,
        payout_profit_usdc: Decimal,
        borrowed_usdc: Decimal,
        lp_share_usdc: Decimal,
        repay_amount_usdc: Decimal,
        platform_usdc_revenue: Decimal,
        zen_balance: Decimal,
        usdc_balance: Decimal,
    ) -> None:
        with self.SessionLocal() as session:
            row = TreasurySnapshotRecord(
                market_id=market_id,
                outcome=outcome,
                stake_zen=stake_zen,
                refund_zen=refund_zen,
                rake_zen=rake_zen,
                payout_profit_usdc=payout_profit_usdc,
                borrowed_usdc=borrowed_usdc,
                lp_share_usdc=lp_share_usdc,
                repay_amount_usdc=repay_amount_usdc,
                platform_usdc_revenue=platform_usdc_revenue,
                zen_balance=zen_balance,
                usdc_balance=usdc_balance,
            )
            session.add(row)
            session.commit()

    def latest_commit_timestamp(self) -> datetime | None:
        with self.SessionLocal() as session:
            result = session.execute(select(func.max(CommitRecord.committed_at))).scalar_one_or_none()
            return result

    def commit_exists(self, idempotency_key: str) -> bool:
        if not idempotency_key:
            return False
        with self.SessionLocal() as session:
            return (
                session.execute(
                    select(func.count(CommitRecord.id)).where(CommitRecord.idempotency_key == idempotency_key)
                ).scalar_one()
                > 0
            )

    def get_replay_offset(self, stream_name: str) -> str | None:
        with self.SessionLocal() as session:
            row = session.get(HedgerReplayOffset, stream_name)
            return row.offset if row else None

    def set_replay_offset(self, stream_name: str, offset: str) -> None:
        with self.SessionLocal() as session:
            row = session.get(HedgerReplayOffset, stream_name)
            if row:
                row.offset = offset
                row.updated_at = datetime.now(UTC)
            else:
                row = HedgerReplayOffset(stream_name=stream_name, offset=offset)
                session.add(row)
            session.commit()

    def get_commits_for_market(self, market_id: str) -> list[CommitRecord]:
        with self.SessionLocal() as session:
            rows = session.execute(
                select(CommitRecord).where(CommitRecord.market_id == market_id).order_by(CommitRecord.committed_at)
            ).scalars()
            return list(rows)

    def mark_market_resolved(self, market_id: str, outcome: str) -> None:
        with self.SessionLocal() as session:
            existing = session.get(ResolvedMarketRecord, market_id)
            if existing:
                existing.outcome = outcome
                existing.resolved_at = datetime.now(UTC)
            else:
                session.add(ResolvedMarketRecord(market_id=market_id, outcome=outcome))
            session.commit()

    def is_market_resolved(self, market_id: str) -> bool:
        with self.SessionLocal() as session:
            return session.get(ResolvedMarketRecord, market_id) is not None

    def load_commit_aggregates(self) -> dict[str, dict]:
        """Return exposure aggregates per market for restart recovery."""

        with self.SessionLocal() as session:
            rows = session.execute(
                select(
                    CommitRecord.market_id,
                    CommitRecord.direction,
                    func.sum(CommitRecord.stake_zen),
                    func.sum(CommitRecord.stake_usd),
                    func.max(CommitRecord.created_at),
                ).group_by(CommitRecord.market_id, CommitRecord.direction)
            ).all()

        aggregates: dict[str, dict] = {}
        for market_id, direction, stake_zen, stake_usd, last_update in rows:
            market = aggregates.setdefault(
                market_id,
                {
                    "yes_zen": Decimal("0"),
                    "no_zen": Decimal("0"),
                    "yes_usd": Decimal("0"),
                    "no_usd": Decimal("0"),
                    "last_update": last_update,
                },
            )
            if last_update and (market["last_update"] is None or last_update > market["last_update"]):
                market["last_update"] = last_update
            if direction == "yes":
                market["yes_zen"] += stake_zen or Decimal("0")
                market["yes_usd"] += stake_usd or Decimal("0")
            else:
                market["no_zen"] += stake_zen or Decimal("0")
                market["no_usd"] += stake_usd or Decimal("0")
        return aggregates

    def load_hedge_totals(self) -> dict[str, Decimal]:
        """Return cumulative hedged USD per market."""

        with self.SessionLocal() as session:
            rows = session.execute(
                select(
                    HedgeActionRecord.market_id,
                    func.sum(HedgeActionRecord.size_usd),
                ).group_by(HedgeActionRecord.market_id)
            ).all()
        return {market_id: total or Decimal("0") for market_id, total in rows}

    def hedge_breakdown(self, market_id: str) -> dict[str, Decimal]:
        """Return borrow vs unwind totals for a market."""

        with self.SessionLocal() as session:
            rows = session.execute(
                select(
                    HedgeActionRecord.is_unwind,
                    func.sum(HedgeActionRecord.size_usd),
                )
                .where(HedgeActionRecord.market_id == market_id)
                .group_by(HedgeActionRecord.is_unwind)
            ).all()
        borrow = Decimal("0")
        unwind = Decimal("0")
        for is_unwind, total in rows:
            if is_unwind:
                unwind += total or Decimal("0")
            else:
                borrow += total or Decimal("0")
        return {"borrowed": borrow, "unwound": unwind}

    def hedge_payloads(self, market_id: str) -> list[dict]:
        with self.SessionLocal() as session:
            rows = (
                session.query(HedgeActionRecord.response_payload)
                .filter(HedgeActionRecord.market_id == market_id, HedgeActionRecord.response_payload.isnot(None))
                .all()
            )
        payloads: list[dict] = []
        for (payload,) in rows:
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads
