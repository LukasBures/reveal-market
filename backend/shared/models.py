from __future__ import annotations

from enum import Enum

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Float, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import declarative_base
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
    outcomes = Column(JSON, nullable=True)
    tags = Column(JSON, nullable=True)
    extra_data = Column(JSON, nullable=True)
    rake_bps = Column(Integer, nullable=True)
    condition_id = Column(String(66), nullable=True)
    question_id = Column(String(128), nullable=True)
    outcome_prices = Column(JSON, nullable=True)
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
    clob_token_ids = Column(JSON, nullable=True)
    image_variants = Column(JSON, nullable=True)
    closes_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    summary = Column(Text, nullable=True)
    summary_source = Column(String(64), nullable=True)
    summary_model = Column(String(64), nullable=True)
    summary_metadata = Column(JSON, nullable=True)
    summary_checked_at = Column(DateTime(timezone=True), nullable=True)
    summary_requested_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


Index("ix_markets_status_category", Market.status, Market.category)
Index("ix_markets_slug", Market.slug)
Index("ix_markets_condition_id", Market.condition_id)


class Resolution(Base):
    __tablename__ = "resolutions"

    condition_id = Column(String(66), primary_key=True, nullable=False)
    market_id = Column(Integer, nullable=True, index=True)
    event_id = Column(String(128), nullable=True, index=True)
    source = Column(String(32), nullable=False, default="conditional_tokens")
    resolved = Column(Boolean, nullable=False, default=False)
    payouts = Column(JSON, nullable=False, default=list)
    winners = Column(JSON, nullable=True)
    outcomes = Column(JSON, nullable=True)
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
    market_id = Column(Integer, nullable=False, index=True)
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
    commitment_id = Column(BigInteger, nullable=False, index=True)
    level = Column(Integer, nullable=False)
    sibling_hash = Column(String(66), nullable=False)


class SettlementProofStatus(str, Enum):
    NONE = "none"
    REQUESTED = "requested"
    GENERATED = "generated"
    FAILED = "failed"


class Settlement(Base):
    __tablename__ = "settlements"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    market_id = Column(Integer, nullable=False, unique=True, index=True)
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
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class QuoteStatusEnum(str, Enum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    EXPIRED = "expired"


class Quote(Base):
    __tablename__ = "quotes"

    quote_id = Column(String(66), primary_key=True, nullable=False)
    status = Column(String(32), nullable=False, default=QuoteStatusEnum.ISSUED.value)
    payload = Column(JSON, nullable=False)
    stake_zen = Column(Numeric(precision=32, scale=8), nullable=False)
    stake_wei = Column(BigInteger, nullable=False)
    fx_scaled = Column(BigInteger, nullable=False)
    zen_usd = Column(Float, nullable=False)
    market_id = Column(String(128), nullable=True, index=True)
    market_address = Column(String(64), nullable=True)
    user_id = Column(String(128), nullable=True, index=True)
    wallet_address = Column(String(64), nullable=True)
    outcome_id = Column(Integer, nullable=True)
    chain_id = Column(BigInteger, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class FactoryEvent(Base):
    __tablename__ = "factory_events"

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    factory_address = Column(String(64), nullable=False, index=True)
    market_address = Column(String(64), nullable=True, index=True)
    event = Column(String(64), nullable=False)
    tx_hash = Column(String(66), nullable=True, index=True)
    block_number = Column(BigInteger, nullable=True)
    block_timestamp = Column(DateTime(timezone=True), nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SettlementReceipt(Base):
    __tablename__ = "settlement_receipts"

    id = Column(BigIntPk, primary_key=True, autoincrement=True)
    market_id = Column(Integer, nullable=False, index=True)
    market_address = Column(String(64), nullable=True, index=True)
    request_id = Column(String(128), nullable=False, index=True)
    proof_hash = Column(String(66), nullable=True)
    public_signals = Column(JSON, nullable=True)
    prover_version = Column(String(64), nullable=True)
    circuit_hash = Column(String(66), nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
