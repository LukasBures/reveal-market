from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

HealthState = Literal["ok", "degraded", "error"]


class HealthComponent(BaseModel):
    status: HealthState
    detail: Optional[str] = None
    latency_ms: Optional[float] = Field(default=None, ge=0)


class HealthResponse(BaseModel):
    status: HealthState
    service: str
    version: str
    timestamp: datetime
    components: Dict[str, HealthComponent]


class MarketBase(BaseModel):
    event_id: str
    title: str
    category: Optional[str] = None
    slug: Optional[str] = None
    metadata_uri: Optional[str] = None
    oracle: str
    factory: Optional[str] = None
    market_address: Optional[str] = None
    status: str = Field(default="commit")
    outcomes: Optional[Any] = None
    extra_data: Optional[Any] = None
    rake_bps: Optional[int] = None
    condition_id: Optional[str] = None
    question_id: Optional[str] = None
    outcome_prices: Optional[Any] = None
    image_url: Optional[str] = None
    closed: Optional[bool] = None
    uma_resolution_status: Optional[str] = None


class MarketCreate(MarketBase):
    """Payload to insert or replace a market record."""


class MarketUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    metadata_uri: Optional[str] = None
    status: Optional[str] = None
    outcomes: Optional[Any] = None
    extra_data: Optional[Any] = None
    rake_bps: Optional[int] = None
    slug: Optional[str] = None
    condition_id: Optional[str] = None
    question_id: Optional[str] = None
    outcome_prices: Optional[Any] = None
    image_url: Optional[str] = None
    closed: Optional[bool] = None
    uma_resolution_status: Optional[str] = None


class MarketRead(MarketBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketStatusBreakdown(BaseModel):
    status: str
    count: int


class ResolutionWinner(BaseModel):
    index: int
    label: Optional[str] = None
    payout: int


class ResolutionSummary(BaseModel):
    source: str
    conditionId: str
    resolved: bool
    outcomes: List[str] = Field(default_factory=list)
    payouts: List[int] = Field(default_factory=list)
    winners: List[ResolutionWinner] = Field(default_factory=list)
    checkedAt: datetime
    marketId: Optional[int] = None
    eventId: Optional[str] = None
    title: Optional[str] = None
    slug: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)
