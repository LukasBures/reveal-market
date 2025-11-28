from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
    cache_stats: dict[str, float] | None = None


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
    resolution: ResolutionSummary | None = None
    caps: MarketCaps | None = None


class MarketStatusBreakdown(BaseModel):
    status: str
    count: int


class MarketCaps(BaseModel):
    max_stake_zen: float
    max_user_stake_per_market_zen: float
    max_market_stake_zen: float
    remaining_user_stake_zen: float | None = None
    remaining_market_stake_zen: float | None = None


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
    winning_outcome_id: int | None = Field(default=None, alias="winningOutcomeId")
    rake_bps: int | None = Field(default=None, alias="rakeBps")
    request_id: str | None = Field(default=None, alias="requestId")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, validate_by_name=True)


class PricingQuoteRequest(BaseModel):
    stake_zen: float = Field(..., gt=0)
    market_id: str | None = Field(default=None, description="Market ID for cap tracking")
    user_id: str | None = Field(default=None, description="User identifier for per-market caps")
    wallet_address: str | None = Field(default=None, description="User wallet to bind quote to")
    outcome_id: int | None = Field(default=None, ge=0, description="Outcome id to bind quote to")
    market_address: str | None = Field(default=None, description="Market contract address")


class PricingQuoteResponse(BaseModel):
    stake_zen: float
    stake_wei: int = 0
    zen_usd: float
    zen_usd_scaled: int = 0
    displayed_odds_multiplier: float
    rake_zen: float
    refund_zen: float
    hedge_usdc: float
    haircut_percent: float
    worsen_percent: float
    rake_percent: float
    total_monetisation: float
    chain_id: int = 0
    max_stake_zen: float | None = None
    max_user_stake_per_market_zen: float | None = None
    max_market_stake_zen: float | None = None
    remaining_user_stake_zen: float | None = None
    remaining_market_stake_zen: float | None = None
    quote_id: str
    expires_at: datetime
    expiry_ts: int = 0
    signature: str
    signer: str
    market_id: str | None = None
    user_id: str | None = None
    wallet_address: str | None = None
    outcome_id: int | None = None
    market_address: str | None = None


class FxQuoteResponse(BaseModel):
    zen_usd: float
    stale: bool = False


class PricingSubmitRequest(BaseModel):
    quote: PricingQuoteResponse
    max_fx_diff_percent: float | None = Field(default=None, ge=0, description="Optional max FX drift percent vs live")


class PricingSubmitResponse(BaseModel):
    quote: PricingQuoteResponse
    current_fx: float
    valid: bool = True


class QuoteRecord(BaseModel):
    quote_id: str = Field(alias="quoteId")
    status: str
    stake_zen: float = Field(alias="stakeZen")
    stake_wei: int = Field(alias="stakeWei")
    fx_scaled: int = Field(alias="fxScaled")
    zen_usd: float = Field(alias="zenUsd")
    market_id: str | None = Field(default=None, alias="marketId")
    market_address: str | None = Field(default=None, alias="marketAddress")
    user_id: str | None = Field(default=None, alias="userId")
    wallet_address: str | None = Field(default=None, alias="walletAddress")
    outcome_id: int | None = Field(default=None, alias="outcomeId")
    chain_id: int | None = Field(default=None, alias="chainId")
    expires_at: datetime = Field(alias="expiresAt")
    consumed_at: datetime | None = Field(default=None, alias="consumedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    payload: dict[str, Any]

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderBookLevel(BaseModel):
    price: Decimal
    size: Decimal


class ClobOrderBookResponse(BaseModel):
    market: str | None = None
    asset_id: str | None = None
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)
    timestamp: datetime | None = None
    min_order_size: Decimal | None = None
    tick_size: Decimal | None = None
    hash: str | None = None

    @classmethod
    def from_summary(cls, summary: Any) -> ClobOrderBookResponse:
        raw = summary.__dict__ if hasattr(summary, "__dict__") else summary
        bids = cls._parse_levels(raw.get("bids") if isinstance(raw, dict) else None)
        asks = cls._parse_levels(raw.get("asks") if isinstance(raw, dict) else None)
        timestamp = raw.get("timestamp") if isinstance(raw, dict) else None
        parsed_ts = cls._parse_timestamp(timestamp)
        return cls(
            market=raw.get("market") if isinstance(raw, dict) else None,
            asset_id=raw.get("asset_id") or raw.get("assetId") if isinstance(raw, dict) else None,
            bids=bids,
            asks=asks,
            timestamp=parsed_ts,
            min_order_size=cls._coerce_decimal(raw.get("min_order_size") if isinstance(raw, dict) else None),
            tick_size=cls._coerce_decimal(raw.get("tick_size") if isinstance(raw, dict) else None),
            hash=raw.get("hash") if isinstance(raw, dict) else None,
        )

    @staticmethod
    def _parse_levels(levels: Any) -> list[OrderBookLevel]:
        if not isinstance(levels, list):
            return []
        parsed: list[OrderBookLevel] = []
        for level in levels:
            if hasattr(level, "__dict__"):
                level = level.__dict__  # type: ignore[assignment]
            if isinstance(level, dict):
                price = ClobOrderBookResponse._coerce_decimal(level.get("price"))
                size = ClobOrderBookResponse._coerce_decimal(level.get("size"))
                if price is not None and size is not None:
                    parsed.append(OrderBookLevel(price=price, size=size))
        return parsed

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None


class TreasurySnapshot(BaseModel):
    id: int
    market_id: str
    outcome: str
    stake_zen: float
    refund_zen: float
    rake_zen: float
    payout_profit_usdc: float
    borrowed_usdc: float
    lp_share_usdc: float
    repay_amount_usdc: float
    platform_usdc_revenue: float
    zen_balance: float
    usdc_balance: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
