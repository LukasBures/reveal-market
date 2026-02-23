from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
    select,
)
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .types import CommitEvent, HedgeInstruction


class Base(DeclarativeBase):
    pass


class CommitRecord(Base):
    __tablename__ = "hedger_commits"
    __table_args__ = (CheckConstraint("direction IN ('yes','no')", name="ck_hedger_commits_direction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    stake_zen: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    stake_usd: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    account: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class HedgeActionRecord(Base):
    __tablename__ = "hedger_hedge_actions"
    __table_args__ = (
        CheckConstraint("action IN ('buy','sell','hold')", name="ck_hedger_hedge_actions_action"),
        CheckConstraint(
            "status IN ('planned','submitted','sent','executed','failed','cancelled')",
            name="ck_hedger_hedge_actions_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    hedge_outcome: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    size_usd: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    slippage_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    target_coverage: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=4), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="planned")
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_unwind: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class AuditLogRecord(Base):
    __tablename__ = "hedger_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    market_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class SettlementRecord(Base):
    __tablename__ = "hedger_settlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    proof_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prover_latency_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_tx: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class HedgerReplayOffset(Base):
    __tablename__ = "hedger_offsets"

    stream_name: Mapped[str] = mapped_column(String, primary_key=True)
    offset: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class ResolvedMarketRecord(Base):
    __tablename__ = "hedger_resolved_markets"

    market_id: Mapped[str] = mapped_column(String, primary_key=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


class TreasurySnapshotRecord(Base):
    __tablename__ = "hedger_treasury_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    stake_zen: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    refund_zen: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    rake_zen: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    payout_profit_usdc: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    borrowed_usdc: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    lp_share_usdc: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    repay_amount_usdc: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    platform_usdc_revenue: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    zen_balance: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    usdc_balance: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now(UTC), nullable=False)


Index(
    "ux_hedger_commits_idempotency_key",
    CommitRecord.idempotency_key,
    unique=True,
    postgresql_where=CommitRecord.idempotency_key.isnot(None),
    sqlite_where=CommitRecord.idempotency_key.isnot(None),
)


def ensure_async_db_url(database_url: str) -> str:
    """
    Normalize database URLs to async drivers so create_async_engine works even if callers pass sync DSNs.
    """

    try:
        url = make_url(database_url)
    except ArgumentError:
        return database_url
    driver = url.drivername or ""
    if driver.startswith("postgresql") and "asyncpg" not in driver:
        url = url.set(drivername="postgresql+asyncpg")
    elif driver.startswith("sqlite") and "aiosqlite" not in driver:
        url = url.set(drivername="sqlite+aiosqlite")
    return url.render_as_string(hide_password=False)


class HedgerRepository:
    """Lightweight Postgres repository used for audit logs and crash recovery."""

    def __init__(self, database_url: str):
        normalized_url = ensure_async_db_url(database_url)
        self.database_url = normalized_url
        self.engine: AsyncEngine = create_async_engine(normalized_url, pool_pre_ping=True)
        self.SessionLocal = async_sessionmaker(bind=self.engine, expire_on_commit=False, class_=AsyncSession)

    async def create_schema(self) -> None:
        async with self.engine.connect() as conn:
            async with conn.begin():
                await conn.run_sync(Base.metadata.create_all)

    async def check_connection(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(select(1))

    async def record_commit(self, commit: CommitEvent, stake_usd: Decimal, idempotency_key: str | None = None) -> None:
        async with self.SessionLocal() as session:
            async with session.begin():
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

    async def record_hedge_instruction(
        self, instruction: HedgeInstruction, response_payload: dict | None = None
    ) -> None:
        async with self.SessionLocal() as session:
            async with session.begin():
                row = HedgeActionRecord(
                    market_id=instruction.market_id,
                    hedge_outcome=instruction.hedge_outcome,
                    action=instruction.action,
                    size_usd=instruction.size_usd,
                    slippage_bps=instruction.slippage_bps,
                    reason=instruction.reason,
                    target_coverage=Decimal(str(instruction.target_coverage)),
                    response_payload=response_payload,
                    is_unwind=1 if instruction.is_unwind else 0,
                )
                session.add(row)

    async def record_audit_log(
        self,
        *,
        event: str,
        actor: str | None,
        market_id: str | None,
        payload: dict | None = None,
    ) -> None:
        async with self.SessionLocal() as session:
            async with session.begin():
                session.add(
                    AuditLogRecord(
                        event=event,
                        actor=actor,
                        market_id=market_id,
                        payload=payload,
                    )
                )

    async def record_settlement(
        self,
        *,
        market_id: str,
        outcome: str,
        proof_payload: dict | None,
        prover_latency_seconds: int | None,
        submitted_tx: str | None,
    ) -> None:
        async with self.SessionLocal() as session:
            async with session.begin():
                row = SettlementRecord(
                    market_id=market_id,
                    outcome=outcome,
                    proof_payload=proof_payload,
                    prover_latency_seconds=prover_latency_seconds,
                    submitted_tx=submitted_tx,
                )
                session.add(row)

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
        async with self.SessionLocal() as session:
            async with session.begin():
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

    async def latest_commit_timestamp(self) -> datetime | None:
        async with self.SessionLocal() as session:
            result = await session.execute(select(func.max(CommitRecord.committed_at)))
            return result.scalar_one_or_none()

    async def commit_exists(self, idempotency_key: str) -> bool:
        if not idempotency_key:
            return False
        async with self.SessionLocal() as session:
            result = await session.execute(
                select(func.count(CommitRecord.id)).where(CommitRecord.idempotency_key == idempotency_key)
            )
            count = result.scalar_one() or 0
            return count > 0

    async def get_replay_offset(self, stream_name: str) -> str | None:
        async with self.SessionLocal() as session:
            row = await session.get(HedgerReplayOffset, stream_name)
            return row.offset if row else None

    async def set_replay_offset(self, stream_name: str, offset: str) -> None:
        async with self.SessionLocal() as session:
            async with session.begin():
                row = await session.get(HedgerReplayOffset, stream_name)
                if row:
                    row.offset = offset
                    row.updated_at = datetime.now(UTC)
                else:
                    session.add(HedgerReplayOffset(stream_name=stream_name, offset=offset))

    async def get_commits_for_market(self, market_id: str) -> list[CommitRecord]:
        async with self.SessionLocal() as session:
            rows = await session.scalars(
                select(CommitRecord).where(CommitRecord.market_id == market_id).order_by(CommitRecord.committed_at)
            )
            return list(rows.all())

    async def mark_market_resolved(self, market_id: str, outcome: str) -> None:
        async with self.SessionLocal() as session:
            async with session.begin():
                existing = await session.get(ResolvedMarketRecord, market_id)
                if existing:
                    existing.outcome = outcome
                    existing.resolved_at = datetime.now(UTC)
                else:
                    session.add(ResolvedMarketRecord(market_id=market_id, outcome=outcome))

    async def is_market_resolved(self, market_id: str) -> bool:
        async with self.SessionLocal() as session:
            return await session.get(ResolvedMarketRecord, market_id) is not None

    async def load_commit_aggregates(self) -> dict[str, dict]:
        """Return exposure aggregates per market for restart recovery."""

        async with self.SessionLocal() as session:
            result = await session.execute(
                select(
                    CommitRecord.market_id,
                    CommitRecord.direction,
                    func.sum(CommitRecord.stake_zen),
                    func.sum(CommitRecord.stake_usd),
                    func.max(CommitRecord.created_at),
                ).group_by(CommitRecord.market_id, CommitRecord.direction)
            )
            rows = result.all()

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

    async def load_hedge_totals(self) -> dict[str, Decimal]:
        """Return cumulative hedged USD per market."""

        async with self.SessionLocal() as session:
            result = await session.execute(
                select(
                    HedgeActionRecord.market_id,
                    HedgeActionRecord.is_unwind,
                    func.sum(HedgeActionRecord.size_usd),
                ).group_by(HedgeActionRecord.market_id, HedgeActionRecord.is_unwind)
            )
            rows = result.all()
        totals: dict[str, Decimal] = {}
        for market_id, is_unwind, total in rows:
            net = totals.get(market_id, Decimal("0"))
            amount = total or Decimal("0")
            net = net - amount if is_unwind else net + amount
            totals[market_id] = net
        return totals

    async def hedge_breakdown(self, market_id: str) -> dict[str, Decimal]:
        """Return borrow vs unwind totals for a market."""

        async with self.SessionLocal() as session:
            result = await session.execute(
                select(
                    HedgeActionRecord.is_unwind,
                    func.sum(HedgeActionRecord.size_usd),
                )
                .where(HedgeActionRecord.market_id == market_id)
                .group_by(HedgeActionRecord.is_unwind)
            )
            rows = result.all()
        borrow = Decimal("0")
        unwind = Decimal("0")
        for is_unwind, total in rows:
            if is_unwind:
                unwind += total or Decimal("0")
            else:
                borrow += total or Decimal("0")
        return {"borrowed": borrow, "unwound": unwind}

    async def hedge_payloads(self, market_id: str) -> list[dict]:
        async with self.SessionLocal() as session:
            result = await session.execute(
                select(HedgeActionRecord.response_payload).where(
                    HedgeActionRecord.market_id == market_id, HedgeActionRecord.response_payload.isnot(None)
                )
            )
            rows = result.all()
        payloads: list[dict] = []
        for (payload,) in rows:
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads
