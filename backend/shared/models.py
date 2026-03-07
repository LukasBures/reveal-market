from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class MarketStatusEnum(StrEnum):
    COMMIT = "commit"
    LOCKED = "locked"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class ResolutionStatusEnum(StrEnum):
    PENDING = "pending_resolution"
    DISPUTED = "disputed"
    FINAL = "final"


class Market(Base):
    __tablename__ = "markets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('commit','locked','settled','cancelled')",
            name="ck_markets_status",
        ),
        CheckConstraint(
            "resolution_status IN ('pending_resolution','disputed','final')",
            name="ck_markets_resolution_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    oracle: Mapped[str] = mapped_column(String(64), nullable=False)
    factory: Mapped[str | None] = mapped_column(String(64), nullable=True)
    onchain_market_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    market_address: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MarketStatusEnum.COMMIT.value)
    public_event_id: Mapped[str | None] = mapped_column(String(8), nullable=True)
    group_slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    event_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    group_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rake_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    condition_id: Mapped[str | None] = mapped_column(String(66), nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
    )
    resolution_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commits_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uma_resolution_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orders_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    market_maker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_min_size: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    price_tick_size: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    enable_order_book: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    image_variants: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume_24h_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    orderbook_volume_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    trades_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @validates("condition_id", "event_id", "market_address", "group_slug", "category", "event_key")
    def _normalize_ids(self, _key: str, value: str | None) -> str | None:
        if value is None:
            return None
        return value.lower()

    outcomes_rel: Mapped[list[MarketOutcome]] = relationship(
        "MarketOutcome",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    tags_rel: Mapped[list[MarketTag]] = relationship(
        "MarketTag",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    clob_tokens_rel: Mapped[list[MarketClobToken]] = relationship(
        "MarketClobToken",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    gamma_metadata_rel: Mapped[MarketGammaMetadata | None] = relationship(
        "MarketGammaMetadata",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="raise",
    )


class MarketOutcome(Base):
    __tablename__ = "market_outcomes"
    __table_args__ = (UniqueConstraint("market_id", "outcome_id", name="ux_market_outcomes_market_outcome"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MarketTag(Base):
    __tablename__ = "market_tags"
    __table_args__ = (UniqueConstraint("market_id", "tag", name="ux_market_tags_market_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag: Mapped[str] = mapped_column(String(128), nullable=False)


class MarketClobToken(Base):
    __tablename__ = "market_clob_tokens"
    __table_args__ = (UniqueConstraint("market_id", "token_id", name="ux_market_clob_tokens_market_token"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_id: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)


class MarketGammaMetadata(Base):
    __tablename__ = "market_gamma_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    gamma_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    closed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    archived: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    group_item_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    group_item_threshold: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enable_order_book: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    order_price_min_tick_size: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    order_min_size: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume_num: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume1mo: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume_clob: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    liquidity: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    liquidity_num: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    liquidity_clob: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    clob_token_id_yes: Mapped[str | None] = mapped_column(String(128), nullable=True)
    clob_token_id_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    accepting_orders: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accepting_orders_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    group_slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    featured: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    best_bid: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    best_ask: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    spread: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @validates("group_slug")
    def _normalize_group_slug(self, _key: str, value: str | None) -> str | None:
        if value is None:
            return None
        return value.lower()


class Resolution(Base):
    __tablename__ = "resolutions"
    __table_args__ = (
        CheckConstraint(
            "market_id IS NOT NULL OR event_id IS NOT NULL",
            name="ck_resolutions_has_market_ref",
        ),
    )

    condition_id: Mapped[str] = mapped_column(String(66), primary_key=True, nullable=False)
    market_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("markets.event_id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="conditional_tokens")
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payouts: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    winners: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    oracle: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(66), nullable=True)
    transaction_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    winning_outcome_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rake_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


Index("ix_resolutions_block_number", Resolution.block_number)


class Commitment(Base):
    __tablename__ = "commitments"
    __table_args__ = (UniqueConstraint("market_id", "ticket_hash", name="ux_commitments_market_ticket_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_address: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_wei: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payout_wei: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    salt: Mapped[str | None] = mapped_column(String(66), nullable=True)
    ticket_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    leaf: Mapped[str] = mapped_column(String(66), nullable=False)
    leaf_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    claim_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    @validates("user_address", "salt", "leaf", "ticket_hash")
    def _normalize_hex(self, _key: str, value: str | None) -> str | None:
        if value is None:
            return None
        return value.lower()


class CommitmentMerklePath(Base):
    __tablename__ = "commitment_merkle_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sibling_hash: Mapped[str] = mapped_column(String(66), nullable=False)


class SettlementProofStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    GENERATING = "generating"
    REQUESTED = "requested"
    GENERATED = "generated"
    FAILED = "failed"


class SettlementSubmissionStatus(StrEnum):
    NONE = "none"
    QUEUED = "queued"
    PROCESSING = "processing"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint(
            "proof_status IN ('none','pending','generating','requested','generated','failed')",
            name="ck_settlements_proof_status",
        ),
        CheckConstraint(
            "submission_status IN ('none','queued','processing','submitted','confirmed','failed')",
            name="ck_settlements_submission_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    merkle_root: Mapped[str | None] = mapped_column(String(66), nullable=True)
    commitments_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_roots: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    batch_counts: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    pool_total_yes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pool_total_no: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_escrow: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_liability: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rake_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    winning_outcome_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    circuit_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    proof_status: Mapped[str] = mapped_column(String(32), nullable=False, default=SettlementProofStatus.NONE.value)
    proof_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proof_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    submission_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SettlementSubmissionStatus.NONE.value
    )
    submission_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    settlement_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    settlement_block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    revision: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HedgerTreasurySnapshot(Base):
    __tablename__ = "hedger_treasury_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("markets.event_id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class QuoteStatusEnum(StrEnum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('issued','consumed','expired')",
            name="ck_quotes_status",
        ),
    )

    quote_id: Mapped[str] = mapped_column(String(66), primary_key=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=QuoteStatusEnum.ISSUED.value)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stake_zen: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    stake_wei: Mapped[Decimal] = mapped_column(Numeric(precision=78, scale=0), nullable=False)
    fx_scaled: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zen_usd: Mapped[Decimal] = mapped_column(Numeric(precision=32, scale=8), nullable=False)
    market_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("markets.event_id", ondelete="SET NULL"), nullable=True, index=True
    )
    market_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    outcome_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chain_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QuoteAudit(Base):
    __tablename__ = "quote_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[str] = mapped_column(
        String(66), ForeignKey("quotes.quote_id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    market_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    market_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chain_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stake_zen: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    stake_wei: Mapped[Decimal | None] = mapped_column(Numeric(precision=78, scale=0), nullable=True)
    fx_scaled: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    zen_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FactoryEvent(Base):
    __tablename__ = "factory_events"
    __table_args__ = (UniqueConstraint("factory_address", "event", "tx_hash", name="ux_factory_events_dedupe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factory_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    market_address: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("markets.market_address", ondelete="SET NULL"), nullable=True, index=True
    )
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True, index=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SettlementReceipt(Base):
    __tablename__ = "settlement_receipts"
    __table_args__ = (UniqueConstraint("market_id", "request_id", name="ux_settlement_receipts_market_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    market_address: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("markets.market_address", ondelete="SET NULL"), nullable=True, index=True
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    proof_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    batch_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    public_signals: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    prover_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    circuit_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proof: Mapped[str | None] = mapped_column(Text, nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Secondary indexes (defined after models to avoid NameError during import)
Index("ix_markets_status_category", Market.status, Market.category)
Index("ix_markets_slug", Market.slug)
Index("ix_markets_public_event_id", Market.public_event_id)
Index("ix_markets_condition_id", Market.condition_id)
Index("ix_markets_resolution_status", Market.resolution_status)
Index("ix_markets_event_key", Market.event_key)
Index("ix_markets_group_slug", Market.group_slug)
Index("ix_markets_closes_at", Market.closes_at)
Index("ix_commitments_user_address", Commitment.user_address)
Index("ix_commitments_claim_tx_hash", Commitment.claim_tx_hash)
Index(
    "ix_quotes_expires_at_issued",
    Quote.expires_at,
    postgresql_where=Quote.status == QuoteStatusEnum.ISSUED.value,
)
Index("ix_settlements_tx_hash", Settlement.settlement_tx_hash)
Index("ix_settlements_proof_status", Settlement.proof_status)
Index("ix_settlements_submission_status", Settlement.submission_status)
Index("ix_commitments_market_leaf", Commitment.market_id, Commitment.leaf_index)
Index("ix_settlement_receipts_request", SettlementReceipt.request_id)
Index("ix_treasury_market_id", HedgerTreasurySnapshot.market_id)

# Phase 1C: Composite & partial indexes
Index("ix_commitments_user_market", Commitment.user_address, Commitment.market_id)
Index("ix_commitments_outcome", Commitment.outcome_id)
Index("ix_quotes_status", Quote.status)
Index("ix_quotes_created_at", Quote.created_at)
Index("ix_markets_featured", Market.featured, postgresql_where=Market.featured.is_(True))

# Phase 4: Normalized-column B-tree indexes & BRIN for append-only timestamps
Index("ix_markets_category", Market.category)
Index("ix_commitments_created_brin", Commitment.created_at, postgresql_using="brin")
# Proof receipts are sorted by generated_at DESC, created_at DESC on every /proofs request.
# Without an index the query requires a full-table sort; this composite covers the ORDER BY.
Index("ix_settlement_receipts_generated_created", SettlementReceipt.generated_at, SettlementReceipt.created_at)
