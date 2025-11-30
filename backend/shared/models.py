from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()
BigIntPk = BigInteger().with_variant(Integer, "sqlite")


class MarketStatusEnum(str, Enum):
    COMMIT = "commit"
    LOCKED = "locked"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class Market(Base):
    __tablename__ = "markets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('commit','locked','settled','cancelled')",
            name="ck_markets_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(128), unique=True, index=True, nullable=False)
    title = Column(String(256), nullable=False)
    slug = Column(String(256), nullable=True)
    category = Column(String(128), nullable=True)
    metadata_uri = Column(String(512), nullable=True)
    oracle = Column(String(64), nullable=False)
    factory = Column(String(64), nullable=True)
    market_address = Column(String(64), unique=True, nullable=True)
    status = Column(String(32), nullable=False, default=MarketStatusEnum.COMMIT.value)
    gamma_raw = Column(JSON, nullable=True)
    group_slug = Column(String(256), nullable=True, index=True)
    group_position = Column(Integer, nullable=True)
    rake_bps = Column(Integer, nullable=True)
    condition_id = Column(String(66), nullable=True)
    question_id = Column(String(128), nullable=True)
    image_url = Column(String(512), nullable=True)
    closed = Column(Boolean, nullable=False, default=False)
    uma_resolution_status = Column(String(64), nullable=True)
    source_updated_at = Column(DateTime(timezone=True), nullable=True)
    content_hash = Column(String(128), nullable=True)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    orders_opened_at = Column(DateTime(timezone=True), nullable=True)
    resolution_source = Column(String(512), nullable=True)
    market_maker = Column(String(64), nullable=True)
    order_min_size = Column(Float, nullable=True)
    price_tick_size = Column(Float, nullable=True)
    enable_order_book = Column(Boolean, nullable=True)
    image_variants = Column(JSON, nullable=True)
    closes_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    summary = Column(Text, nullable=True)
    summary_source = Column(String(64), nullable=True)
    summary_model = Column(String(64), nullable=True)
    summary_metadata = Column(JSON, nullable=True)
    summary_checked_at = Column(DateTime(timezone=True), nullable=True)
    summary_requested_at = Column(DateTime(timezone=True), nullable=True)
    liquidity_usd = Column(Numeric(precision=32, scale=8), nullable=True)
    volume_24h_usd = Column(Numeric(precision=32, scale=8), nullable=True)
    orderbook_volume_usd = Column(Numeric(precision=32, scale=8), nullable=True)
    trades_quantity = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    outcomes_rel = relationship(
        "MarketOutcome",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    tags_rel = relationship(
        "MarketTag",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    clob_tokens_rel = relationship(
        "MarketClobToken",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    gamma_metadata_rel = relationship(
        "MarketGammaMetadata",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )
    gamma_events_rel = relationship(
        "MarketGammaEvent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class MarketOutcome(Base):
    __tablename__ = "market_outcomes"
    __table_args__ = (UniqueConstraint("market_id", "outcome_id", name="ux_market_outcomes_market_outcome"),)

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True)
    outcome_id = Column(Integer, nullable=False)
    label = Column(String(256), nullable=False)
    price = Column(Numeric(precision=32, scale=8), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MarketTag(Base):
    __tablename__ = "market_tags"
    __table_args__ = (UniqueConstraint("market_id", "tag", name="ux_market_tags_market_tag"),)

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True)
    tag = Column(String(128), nullable=False)


class MarketClobToken(Base):
    __tablename__ = "market_clob_tokens"
    __table_args__ = (UniqueConstraint("market_id", "token_id", name="ux_market_clob_tokens_market_token"),)

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True)
    token_id = Column(String(128), nullable=False)
    side = Column(String(8), nullable=True)


class MarketGammaMetadata(Base):
    __tablename__ = "market_gamma_metadata"

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, unique=True)
    gamma_id = Column(String(64), nullable=True)
    question = Column(Text, nullable=True)
    slug = Column(String(256), nullable=True)
    resolution_source = Column(String(512), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    image = Column(String(512), nullable=True)
    icon = Column(String(512), nullable=True)
    description = Column(Text, nullable=True)
    liquidity = Column(Numeric(precision=32, scale=8), nullable=True)
    volume = Column(Numeric(precision=32, scale=8), nullable=True)
    active = Column(Boolean, nullable=True)
    closed = Column(Boolean, nullable=True)
    market_maker_address = Column(String(128), nullable=True)
    created_at_raw = Column(DateTime(timezone=True), nullable=True)
    updated_at_raw = Column(DateTime(timezone=True), nullable=True)
    submitted_by = Column(String(128), nullable=True)
    archived = Column(Boolean, nullable=True)
    resolved_by = Column(String(128), nullable=True)
    restricted = Column(Boolean, nullable=True)
    group_item_title = Column(String(256), nullable=True)
    group_item_threshold = Column(String(64), nullable=True)
    question_id = Column(String(128), nullable=True)
    enable_order_book = Column(Boolean, nullable=True)
    order_price_min_tick_size = Column(Float, nullable=True)
    order_min_size = Column(Float, nullable=True)
    volume_num = Column(Numeric(precision=32, scale=8), nullable=True)
    liquidity_num = Column(Numeric(precision=32, scale=8), nullable=True)
    group_slug = Column(String(256), nullable=True, index=True)
    end_date_iso = Column(String(64), nullable=True)
    start_date_iso = Column(String(64), nullable=True)
    has_reviewed_dates = Column(Boolean, nullable=True)
    volume1mo = Column(Numeric(precision=32, scale=8), nullable=True)
    volume1yr = Column(Numeric(precision=32, scale=8), nullable=True)
    clob_token_id_yes = Column(String(128), nullable=True)
    clob_token_id_no = Column(String(128), nullable=True)
    uma_bond = Column(Numeric(precision=32, scale=8), nullable=True)
    uma_reward = Column(Numeric(precision=32, scale=8), nullable=True)
    volume1mo_clob = Column(Numeric(precision=32, scale=8), nullable=True)
    volume1yr_clob = Column(Numeric(precision=32, scale=8), nullable=True)
    volume_clob = Column(Numeric(precision=32, scale=8), nullable=True)
    liquidity_clob = Column(Numeric(precision=32, scale=8), nullable=True)
    custom_liveness = Column(Integer, nullable=True)
    accepting_orders = Column(Boolean, nullable=True)
    neg_risk = Column(Boolean, nullable=True)
    neg_risk_market_id = Column(String(128), nullable=True)
    neg_risk_request_id = Column(String(128), nullable=True)
    ready = Column(Boolean, nullable=True)
    funded = Column(Boolean, nullable=True)
    accepting_orders_timestamp = Column(DateTime(timezone=True), nullable=True)
    competitive = Column(Float, nullable=True)
    pagerduty_enabled = Column(Boolean, nullable=True)
    approved = Column(Boolean, nullable=True)
    rewards_min_size = Column(Numeric(precision=32, scale=8), nullable=True)
    rewards_max_spread = Column(Numeric(precision=32, scale=8), nullable=True)
    spread = Column(Float, nullable=True)
    one_day_price_change = Column(Float, nullable=True)
    one_week_price_change = Column(Float, nullable=True)
    one_month_price_change = Column(Float, nullable=True)
    last_trade_price = Column(Float, nullable=True)
    best_bid = Column(Float, nullable=True)
    best_ask = Column(Float, nullable=True)
    clear_book_on_start = Column(Boolean, nullable=True)
    manual_activation = Column(Boolean, nullable=True)
    neg_risk_other = Column(Boolean, nullable=True)
    uma_resolution_statuses = Column(Text, nullable=True)
    pending_deployment = Column(Boolean, nullable=True)
    deploying = Column(Boolean, nullable=True)
    deploying_timestamp = Column(DateTime(timezone=True), nullable=True)
    rfq_enabled = Column(Boolean, nullable=True)
    holding_rewards_enabled = Column(Boolean, nullable=True)
    fees_enabled = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MarketGammaEvent(Base):
    __tablename__ = "market_gamma_events"

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String(64), nullable=True)
    ticker = Column(String(128), nullable=True)
    slug = Column(String(256), nullable=True)
    title = Column(String(512), nullable=True)
    description = Column(Text, nullable=True)
    resolution_source = Column(String(512), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    image = Column(String(512), nullable=True)
    icon = Column(String(512), nullable=True)
    active = Column(Boolean, nullable=True)
    closed = Column(Boolean, nullable=True)
    archived = Column(Boolean, nullable=True)
    new = Column(Boolean, nullable=True)
    featured = Column(Boolean, nullable=True)
    restricted = Column(Boolean, nullable=True)
    liquidity = Column(Numeric(precision=32, scale=8), nullable=True)
    volume = Column(Numeric(precision=32, scale=8), nullable=True)
    open_interest = Column(Numeric(precision=32, scale=8), nullable=True)
    sort_by = Column(String(64), nullable=True)
    created_at_raw = Column(DateTime(timezone=True), nullable=True)
    updated_at_raw = Column(DateTime(timezone=True), nullable=True)
    competitive = Column(Float, nullable=True)
    volume_1wk = Column(Numeric(precision=32, scale=8), nullable=True)
    volume_1mo = Column(Numeric(precision=32, scale=8), nullable=True)
    volume_1yr = Column(Numeric(precision=32, scale=8), nullable=True)
    enable_order_book = Column(Boolean, nullable=True)
    liquidity_clob = Column(Numeric(precision=32, scale=8), nullable=True)
    neg_risk = Column(Boolean, nullable=True)
    neg_risk_market_id = Column(String(128), nullable=True)
    comment_count = Column(Integer, nullable=True)
    cyom = Column(Boolean, nullable=True)
    show_all_outcomes = Column(Boolean, nullable=True)
    show_market_images = Column(Boolean, nullable=True)
    enable_neg_risk = Column(Boolean, nullable=True)
    automatically_active = Column(Boolean, nullable=True)
    neg_risk_augmented = Column(Boolean, nullable=True)
    pending_deployment = Column(Boolean, nullable=True)
    deploying = Column(Boolean, nullable=True)
    deploying_timestamp = Column(DateTime(timezone=True), nullable=True)
    competitive_flags = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Resolution(Base):
    __tablename__ = "resolutions"

    condition_id = Column(String(66), primary_key=True, nullable=False)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="SET NULL"), nullable=True, index=True)
    event_id = Column(String(128), ForeignKey("markets.event_id", ondelete="SET NULL"), nullable=True, index=True)
    source = Column(String(32), nullable=False, default="conditional_tokens")
    resolved = Column(Boolean, nullable=False, default=False)
    payouts = Column(JSON, nullable=False, default=list)
    winners = Column(JSON, nullable=True)
    oracle = Column(String(64), nullable=True)
    question_id = Column(String(66), nullable=True)
    transaction_hash = Column(String(66), nullable=True)
    block_number = Column(BigInteger, nullable=True)
    block_timestamp = Column(DateTime(timezone=True), nullable=True)
    winning_outcome_id = Column(Integer, nullable=True)
    rake_bps = Column(Integer, nullable=True)
    request_id = Column(String(128), nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


Index("ix_resolutions_block_number", Resolution.block_number)


class Commitment(Base):
    __tablename__ = "commitments"

    id = Column(BigIntPk, primary_key=True, index=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True)
    user_address = Column(String(64), nullable=False)
    outcome_id = Column(Integer, nullable=False)
    amount_wei = Column(BigInteger, nullable=False)
    salt = Column(String(66), nullable=True)
    ticket_hash = Column(String(66), nullable=False)
    leaf = Column(String(66), nullable=False)
    leaf_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CommitmentMerklePath(Base):
    __tablename__ = "commitment_merkle_paths"

    id = Column(BigIntPk, primary_key=True, index=True, autoincrement=True)
    commitment_id = Column(BigInteger, ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(Integer, nullable=False)
    sibling_hash = Column(String(66), nullable=False)


class SettlementProofStatus(str, Enum):
    NONE = "none"
    REQUESTED = "requested"
    GENERATED = "generated"
    FAILED = "failed"


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint(
            "proof_status IN ('none','requested','generated','failed')",
            name="ck_settlements_proof_status",
        ),
    )

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    merkle_root = Column(String(66), nullable=True)
    commitments_count = Column(Integer, nullable=True)
    pool_total_yes = Column(BigInteger, nullable=True)
    pool_total_no = Column(BigInteger, nullable=True)
    total_escrow = Column(BigInteger, nullable=True)
    total_liability = Column(BigInteger, nullable=True)
    rake_bps = Column(Integer, nullable=True)
    winning_outcome_id = Column(Integer, nullable=True)
    circuit_hash = Column(String(66), nullable=True)
    proof_status = Column(String(32), nullable=False, default=SettlementProofStatus.NONE.value)
    proof_request_id = Column(String(128), nullable=True)
    proof_hash = Column(String(66), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    key = Column(String(64), primary_key=True, nullable=False)
    revision = Column(String(64), nullable=False)
    applied_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HedgerTreasurySnapshot(Base):
    __tablename__ = "hedger_treasury_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market_id = Column(String(128), ForeignKey("markets.event_id", ondelete="CASCADE"), nullable=False, index=True)
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
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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

    quote_id = Column(String(66), primary_key=True, nullable=False)
    status = Column(String(32), nullable=False, default=QuoteStatusEnum.ISSUED.value)
    payload = Column(JSON, nullable=False)
    stake_zen = Column(Numeric(precision=32, scale=8), nullable=False)
    stake_wei = Column(Numeric(precision=78, scale=0), nullable=False)
    fx_scaled = Column(BigInteger, nullable=False)
    zen_usd = Column(Float, nullable=False)
    market_id = Column(String(128), ForeignKey("markets.event_id", ondelete="SET NULL"), nullable=True, index=True)
    market_address = Column(String(64), nullable=True)
    user_id = Column(String(128), nullable=True, index=True)
    wallet_address = Column(String(64), nullable=True, index=True)
    outcome_id = Column(Integer, nullable=True)
    chain_id = Column(BigInteger, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class FactoryEvent(Base):
    __tablename__ = "factory_events"
    __table_args__ = (UniqueConstraint("factory_address", "event", "tx_hash", name="ux_factory_events_dedupe"),)

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    factory_address = Column(String(64), nullable=False, index=True)
    market_address = Column(
        String(64), ForeignKey("markets.market_address", ondelete="SET NULL"), nullable=True, index=True
    )
    event = Column(String(64), nullable=False)
    tx_hash = Column(String(66), nullable=True, index=True)
    block_number = Column(BigInteger, nullable=True)
    block_timestamp = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SettlementReceipt(Base):
    __tablename__ = "settlement_receipts"
    __table_args__ = (UniqueConstraint("market_id", "request_id", name="ux_settlement_receipts_market_request"),)

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    market_id = Column(Integer, ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True)
    market_address = Column(
        String(64), ForeignKey("markets.market_address", ondelete="SET NULL"), nullable=True, index=True
    )
    request_id = Column(String(128), nullable=False, index=True)
    proof_hash = Column(String(66), nullable=True)
    public_signals = Column(JSON, nullable=True)
    prover_version = Column(String(64), nullable=True)
    circuit_hash = Column(String(66), nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# Secondary indexes (defined after models to avoid NameError during import)
Index("ix_markets_status_category", Market.status, Market.category)
Index("ix_markets_slug", Market.slug)
Index("ix_markets_condition_id", Market.condition_id)
Index("ix_commitments_user_address", Commitment.user_address)
Index(
    "ix_quotes_expires_at_issued",
    Quote.expires_at,
    postgresql_where=Quote.status == QuoteStatusEnum.ISSUED.value,
)
