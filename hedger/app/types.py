from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


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

    model_config = ConfigDict(use_enum_values=True, str_strip_whitespace=True, frozen=True, populate_by_name=True)

    class SignedQuotePayload(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True)

        quote_id: str
        stake_wei: int
        zen_usd_scaled: int
        expiry_ts: int
        chain_id: int
        market_address: str
        wallet_address: str
        outcome_id: int
        signature: str

    market_id: str = Field(..., description="RevealMarket identifier")
    stake_zen: Decimal = Field(..., description="Commit stake in ZEN")
    direction: OutcomeSide = Field(..., description="Outcome chosen off-chain (kept private on-chain)")
    category: str | None = Field(default=None, description="Market category (optional for exposure limits)")
    committed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tx_hash: str | None = Field(default=None, description="Commit transaction hash")
    account: str | None = Field(default=None, description="Committer wallet (hash or pseudonymized)")
    request_id: str | None = Field(default=None, description="Trace identifier for correlating logs")
    metadata_source: str | None = Field(default=None, description="Origin of the off-chain direction hint")
    idempotency_key: str | None = Field(default=None, description="Unique key for replay-safe ingestion")
    stream_offset: str | None = Field(default=None, description="Event offset for replay checkpoints")
    market_address: str | None = Field(default=None, description="On-chain market address")
    outcome_id: int | None = Field(default=None, description="Outcome id used for the commitment")
    wallet_address: str | None = Field(default=None, description="Wallet that submitted the on-chain commit")
    signed_quote: SignedQuotePayload | None = Field(
        default=None,
        description="Pricing quote payload that matches the on-chain commit",
        alias="quote",
    )


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


class PricingQuote(BaseModel):
    """User-facing economics for a ZEN bet."""

    stake_zen: Decimal
    zen_usd: Decimal
    displayed_odds_multiplier: Decimal
    rake_zen: Decimal
    refund_zen: Decimal
    hedge_usdc: Decimal
    haircut_percent: Decimal
    worsen_percent: Decimal
    rake_percent: Decimal
    total_monetisation: Decimal

    @computed_field(return_type=Decimal)  # type: ignore[misc]
    @property
    def total_monetization(self) -> Decimal:
        """US spelling alias for downstream callers and JSON serialization."""
        return self.total_monetisation


class SettlementBreakdown(BaseModel):
    """Settlement outputs for a single bet."""

    stake_zen: Decimal
    refund_zen: Decimal
    rake_zen: Decimal
    payout_profit_usdc: Decimal
    borrowed_usdc: Decimal
    lp_share_usdc: Decimal
    repay_amount_usdc: Decimal
    total_platform_usdc_revenue: Decimal
    user_outcome: str


class TreasurySnapshot(BaseModel):
    """Current balances for the split treasuries."""

    zen_balance: Decimal
    usdc_balance: Decimal
