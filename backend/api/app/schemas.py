from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field


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
    pass


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

    class Config:
        orm_mode = True
