from __future__ import annotations

from enum import Enum

from sqlalchemy import Column, DateTime, Integer, String, JSON, Index
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
    category = Column(String(128), nullable=True)
    metadata_uri = Column(String(512), nullable=True)
    oracle = Column(String(64), nullable=False)
    factory = Column(String(64), nullable=True)
    market_address = Column(String(64), unique=True, nullable=True)
    status = Column(String(32), nullable=False, default=MarketStatusEnum.COMMIT.value)
    outcomes = Column(JSON, nullable=True)
    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


Index("ix_markets_status_category", Market.status, Market.category)
