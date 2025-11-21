from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OutcomeSide(str, Enum):
    YES = "yes"
    NO = "no"


class HedgeAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class RiskSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class CommitEvent(BaseModel):
    """Commit observed from Horizen plus off-chain metadata."""

    model_config = ConfigDict(use_enum_values=True, str_strip_whitespace=True, frozen=True)

    market_id: str = Field(..., description="RevealMarket identifier")
    stake_zen: Decimal = Field(..., description="Commit stake in ZEN")
    direction: OutcomeSide = Field(..., description="Outcome chosen off-chain (kept private on-chain)")
    committed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tx_hash: str | None = Field(default=None, description="Commit transaction hash")
    account: str | None = Field(default=None, description="Committer wallet (hash or pseudonymized)")
    request_id: str | None = Field(default=None, description="Trace identifier for correlating logs")
    metadata_source: str | None = Field(default=None, description="Origin of the off-chain direction hint")
    idempotency_key: str | None = Field(default=None, description="Unique key for replay-safe ingestion")
    stream_offset: str | None = Field(default=None, description="Event offset for replay checkpoints")


class MarketExposureSnapshot(BaseModel):
    """Current book state for a market."""

    model_config = ConfigDict(use_enum_values=True)

    market_id: str
    yes_zen: Decimal
    no_zen: Decimal
    yes_usd: Decimal
    no_usd: Decimal
    net_zen: Decimal
    net_usd: Decimal
    hedged_usd: Decimal
    coverage_ratio: float
    last_update: datetime


class HedgeInstruction(BaseModel):
    """Action required on Polymarket/Base to stay delta-neutral."""

    model_config = ConfigDict(use_enum_values=True)

    market_id: str
    hedge_outcome: OutcomeSide
    action: HedgeAction
    size_usd: Decimal
    slippage_bps: int
    reason: str
    target_coverage: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_unwind: bool = Field(default=False, description="Whether this instruction reduces an existing hedge")


class RiskBreach(BaseModel):
    """Flag emitted when limits are exceeded."""

    model_config = ConfigDict(use_enum_values=True)

    code: str
    severity: RiskSeverity
    message: str
    market_id: str | None = None
    detail: dict[str, Any] | None = None
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskReport(BaseModel):
    """Current risk status across the hedger."""

    breaches: list[RiskBreach]
    max_global_exposure_usd: Decimal
    max_per_market_usd: Decimal
    coverage_ratio_target: float
    lp_utilization_limit: float
    float_min_zen: Decimal


@dataclass(slots=True)
class FxQuote:
    zen_usd: Decimal
    fetched_at: datetime
