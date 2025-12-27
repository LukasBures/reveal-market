from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


BigIntPk = BigInteger().with_variant(Integer, "sqlite")


class MarketStatusEnum(str, Enum):
    COMMIT = "commit"
    LOCKED = "locked"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class ResolutionStatusEnum(str, Enum):
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
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    oracle: Mapped[str] = mapped_column(String(64), nullable=False)
    factory: Mapped[str | None] = mapped_column(String(64), nullable=True)
    onchain_market_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    market_address: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MarketStatusEnum.COMMIT.value)
    gamma_raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    group_slug: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
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
    order_min_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    enable_order_book: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    image_variants: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    summary_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    liquidity_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume_24h_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    orderbook_volume_usd: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    trades_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    outcomes_rel: Mapped[list[MarketOutcome]] = relationship(
        "MarketOutcome",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    tags_rel: Mapped[list[MarketTag]] = relationship(
        "MarketTag",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    clob_tokens_rel: Mapped[list[MarketClobToken]] = relationship(
        "MarketClobToken",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    gamma_metadata_rel: Mapped[MarketGammaMetadata | None] = relationship(
        "MarketGammaMetadata",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )
    gamma_events_rel: Mapped[list[MarketGammaEvent]] = relationship(
        "MarketGammaEvent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class MarketOutcome(Base):
    __tablename__ = "market_outcomes"
    __table_args__ = (UniqueConstraint("market_id", "outcome_id", name="ux_market_outcomes_market_outcome"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
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

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag: Mapped[str] = mapped_column(String(128), nullable=False)


class MarketClobToken(Base):
    __tablename__ = "market_clob_tokens"
    __table_args__ = (UniqueConstraint("market_id", "token_id", name="ux_market_clob_tokens_market_token"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_id: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)


class MarketGammaMetadata(Base):
    __tablename__ = "market_gamma_metadata"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
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
    liquidity: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    closed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    market_maker_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at_raw: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_raw: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    archived: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    group_item_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    group_item_threshold: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enable_order_book: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    order_price_min_tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_min_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_num: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    liquidity_num: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    group_slug: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    end_date_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_date_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    has_reviewed_dates: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    volume1mo: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume1yr: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    clob_token_id_yes: Mapped[str | None] = mapped_column(String(128), nullable=True)
    clob_token_id_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uma_bond: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    uma_reward: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume1mo_clob: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume1yr_clob: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume_clob: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    liquidity_clob: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    custom_liveness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepting_orders: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    neg_risk: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    neg_risk_market_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    neg_risk_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ready: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    funded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    accepting_orders_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    competitive: Mapped[float | None] = mapped_column(Float, nullable=True)
    pagerduty_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    featured: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rewards_min_size: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    rewards_max_spread: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    one_day_price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    one_week_price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    one_month_price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    clear_book_on_start: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    manual_activation: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    neg_risk_other: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    uma_resolution_statuses: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_deployment: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deploying: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deploying_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rfq_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    holding_rewards_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fees_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MarketGammaEvent(Base):
    __tablename__ = "market_gamma_events"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(128), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image: Mapped[str | None] = mapped_column(String(512), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(512), nullable=True)
    active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    closed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    archived: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    new: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    featured: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    restricted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    liquidity: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    sort_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at_raw: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_raw: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    competitive: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_1wk: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume_1mo: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    volume_1yr: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    enable_order_book: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    liquidity_clob: Mapped[Decimal | None] = mapped_column(Numeric(precision=32, scale=8), nullable=True)
    neg_risk: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    neg_risk_market_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cyom: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    show_all_outcomes: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    show_market_images: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enable_neg_risk: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    automatically_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    neg_risk_augmented: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pending_deployment: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deploying: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deploying_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    competitive_flags: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Resolution(Base):
    __tablename__ = "resolutions"

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

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, index=True, autoincrement=True)
    market_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_address: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_wei: Mapped[int] = mapped_column(BigInteger, nullable=False)
    salt: Mapped[str | None] = mapped_column(String(66), nullable=True)
    ticket_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    leaf: Mapped[str] = mapped_column(String(66), nullable=False)
    leaf_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    claim_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CommitmentMerklePath(Base):
    __tablename__ = "commitment_merkle_paths"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, index=True, autoincrement=True)
    commitment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    sibling_hash: Mapped[str] = mapped_column(String(66), nullable=False)


class SettlementProofStatus(str, Enum):
    NONE = "none"
    REQUESTED = "requested"
    GENERATED = "generated"
    FAILED = "failed"


class SettlementSubmissionStatus(str, Enum):
    NONE = "none"
    QUEUED = "queued"
    PROCESSING = "processing"
    SUBMITTED = "submitted"
    FAILED = "failed"


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint(
            "proof_status IN ('none','requested','generated','failed')",
            name="ck_settlements_proof_status",
        ),
        CheckConstraint(
            "submission_status IN ('none','queued','processing','submitted','failed')",
            name="ck_settlements_submission_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True, autoincrement=True)
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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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


class QuoteStatusEnum(str, Enum):
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
    zen_usd: Mapped[float] = mapped_column(Float, nullable=False)
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


class FactoryEvent(Base):
    __tablename__ = "factory_events"
    __table_args__ = (UniqueConstraint("factory_address", "event", "tx_hash", name="ux_factory_events_dedupe"),)

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
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

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
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
    proof: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# Secondary indexes (defined after models to avoid NameError during import)
Index("ix_markets_status_category", Market.status, Market.category)
Index("ix_markets_slug", Market.slug)
Index("ix_markets_condition_id", Market.condition_id)
Index("ix_markets_resolution_status", Market.resolution_status)
Index("ix_commitments_user_address", Commitment.user_address)
Index("ix_commitments_claim_tx_hash", Commitment.claim_tx_hash)
Index(
    "ix_quotes_expires_at_issued",
    Quote.expires_at,
    postgresql_where=Quote.status == QuoteStatusEnum.ISSUED.value,
)
Index("ix_settlements_tx_hash", Settlement.settlement_tx_hash)
