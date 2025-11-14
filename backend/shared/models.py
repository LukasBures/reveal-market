from __future__ import annotations

from enum import Enum

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


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
    checked_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    key = Column(String(64), primary_key=True, nullable=False)
    revision = Column(String(64), nullable=False)
    applied_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
