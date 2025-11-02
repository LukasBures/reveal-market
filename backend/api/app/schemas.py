from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

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
    metadata_uri: Optional[str] = None
    oracle: str
    factory: Optional[str] = None
    market_address: Optional[str] = None
    status: str = Field(default="commit")
    outcomes: Optional[Any] = None
    extra_data: Optional[Any] = None


class MarketCreate(MarketBase):
    """Payload to insert or replace a market record."""


class MarketUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    metadata_uri: Optional[str] = None
    status: Optional[str] = None
    outcomes: Optional[Any] = None
    extra_data: Optional[Any] = None


class MarketRead(MarketBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketStatusBreakdown(BaseModel):
    status: str
    count: int
