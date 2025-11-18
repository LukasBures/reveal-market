from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HealthState = Literal["ok", "degraded", "error"]


class HealthComponent(BaseModel):
    status: HealthState
    detail: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)


class HealthResponse(BaseModel):
    status: HealthState
    service: str
    version: str
    timestamp: datetime
    components: dict[str, HealthComponent]


class HeartbeatMetrics(BaseModel):
    service: str
    component: str
    status: HealthState
    last_heartbeat: datetime | None = None
    latency_ms: float | None = None
    detail: str | None = None
    metrics: dict[str, Any] | None = None


class HeartbeatDashboard(BaseModel):
    generated_at: datetime
    worker: HeartbeatMetrics | None = None
    api: HeartbeatMetrics | None = None


class MarketBase(BaseModel):
    event_id: str
    title: str
    category: str | None = None
    slug: str | None = None
    metadata_uri: str | None = None
    oracle: str
    factory: str | None = None
    market_address: str | None = None
    status: str = Field(default="commit")
    outcomes: Any | None = None
    tags: list[str] | None = None
    extra_data: Any | None = None
    rake_bps: int | None = None
    condition_id: str | None = None
    question_id: str | None = None
    outcome_prices: Any | None = None
    image_url: str | None = None
    closed: bool | None = None
    uma_resolution_status: str | None = None
    closes_at: datetime | None = None
    starts_at: datetime | None = None
    orders_opened_at: datetime | None = None
    resolution_source: str | None = None
    market_maker: str | None = None
    order_min_size: float | None = None
    price_tick_size: float | None = None
    enable_order_book: bool | None = None
    clob_token_ids: list[str] | None = None
    image_variants: list[str] | None = None
    summary: str | None = None
    summary_source: str | None = None
    summary_model: str | None = None
    summary_metadata: dict[str, Any] | None = None
    summary_checked_at: datetime | None = None


class MarketCreate(MarketBase):
    """Payload to insert or replace a market record."""


class MarketUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    metadata_uri: str | None = None
    status: str | None = None
    outcomes: Any | None = None
    tags: list[str] | None = None
    extra_data: Any | None = None
    rake_bps: int | None = None
    slug: str | None = None
    condition_id: str | None = None
    question_id: str | None = None
    outcome_prices: Any | None = None
    image_url: str | None = None
    closed: bool | None = None
    uma_resolution_status: str | None = None
    closes_at: datetime | None = None
    starts_at: datetime | None = None
    orders_opened_at: datetime | None = None
    resolution_source: str | None = None
    market_maker: str | None = None
    order_min_size: float | None = None
    price_tick_size: float | None = None
    enable_order_book: bool | None = None
    clob_token_ids: list[str] | None = None
    image_variants: list[str] | None = None


class MarketRead(MarketBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketResponse(MarketRead):
    description: str | None = None
    clob_pair_id: str | None = None


class MarketStatusBreakdown(BaseModel):
    status: str
    count: int


class ResolutionWinner(BaseModel):
    index: int
    label: str | None = None
    payout: int


class ResolutionSummary(BaseModel):
    source: str
    condition_id: str = Field(alias="conditionId")
    resolved: bool
    outcomes: list[str] = Field(default_factory=list)
    payouts: list[int] = Field(default_factory=list)
    winners: list[ResolutionWinner] = Field(default_factory=list)
    checked_at: datetime = Field(alias="checkedAt")
    market_id: int | None = Field(default=None, alias="marketId")
    event_id: str | None = Field(default=None, alias="eventId")
    title: str | None = None
    slug: str | None = None
    oracle: str | None = None
    question_id: str | None = Field(default=None, alias="questionId")
    transaction_hash: str | None = Field(default=None, alias="transactionHash")
    block_number: int | None = Field(default=None, alias="blockNumber")
    block_timestamp: datetime | None = Field(default=None, alias="blockTimestamp")

    model_config = ConfigDict(populate_by_name=True, validate_by_name=True)
