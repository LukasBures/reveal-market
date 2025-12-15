from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

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
    outcomes: list[str] | None = None
    outcome_prices: list[float] | None = None
    tags: list[str] | None = None
    rake_bps: int | None = None
    condition_id: str | None = None
    question_id: str | None = None
    image_url: str | None = None
    closed: bool | None = None
    resolution_status: str | None = None
    resolution_reason: str | None = None
    commits_blocked_at: datetime | None = None
    uma_resolution_status: str | None = None
    closes_at: datetime | None = None
    starts_at: datetime | None = None
    orders_opened_at: datetime | None = None
    resolution_source: str | None = None
    market_maker: str | None = None
    order_min_size: Decimal | None = None
    price_tick_size: Decimal | None = None
    enable_order_book: bool | None = None
    clob_token_ids: list[str] | None = None
    image_variants: list[str] | None = None
    featured: bool | None = None
    group_slug: str | None = None
    group_item_title: str | None = None
    group_item_threshold: float | None = None
    group_position: int | None = None
    summary: str | None = None
    summary_source: str | None = None
    summary_model: str | None = None
    summary_metadata: dict[str, Any] | None = None
    summary_checked_at: datetime | None = None
    liquidity_usd: float | None = None
    volume_24h_usd: float | None = None
    orderbook_volume_usd: float | None = None
    trades_quantity: int | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    volume: float | None = None
    open_interest: float | None = None


class MarketCreate(MarketBase):
    """Payload to insert or replace a market record."""


class MarketUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    metadata_uri: str | None = None
    status: str | None = None
    outcomes: list[str] | None = None
    tags: list[str] | None = None
    rake_bps: int | None = None
    slug: str | None = None
    condition_id: str | None = None
    question_id: str | None = None
    outcome_prices: list[float] | None = None
    image_url: str | None = None
    closed: bool | None = None
    resolution_status: str | None = None
    resolution_reason: str | None = None
    commits_blocked_at: datetime | None = None
    uma_resolution_status: str | None = None
    closes_at: datetime | None = None
    starts_at: datetime | None = None
    orders_opened_at: datetime | None = None
    resolution_source: str | None = None
    market_maker: str | None = None
    order_min_size: Decimal | None = None
    price_tick_size: Decimal | None = None
    enable_order_book: bool | None = None
    clob_token_ids: list[str] | None = None
    image_variants: list[str] | None = None


class MarketRead(MarketBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketSibling(BaseModel):
    event_id: str
    title: str | None = None
    group_item_title: str | None = None
    group_item_threshold: float | None = None
    group_position: int | None = None
    outcome_prices: list[float] | None = None
    liquidity_usd: float | None = None
    volume_24h_usd: float | None = None

    model_config = ConfigDict(from_attributes=True)


class MarketResponse(MarketRead):
    description: str | None = None
    clob_pair_id: str | None = None
    resolution: ResolutionSummary | None = None
    caps: MarketCaps | None = None
    siblings: list[MarketSibling] | None = None


class MarketStatusBreakdown(BaseModel):
    status: str
    count: int


class GroupedMarketsResponse(BaseModel):
    group_slug: str
    markets: list[MarketResponse]
    aggregate_volume_24h_usd: float | None = None
    aggregate_liquidity_usd: float | None = None


class MarketCaps(BaseModel):
    max_stake_zen: Decimal
    max_user_stake_per_market_zen: Decimal
    max_market_stake_zen: Decimal
    remaining_user_stake_zen: Decimal | None = None
    remaining_market_stake_zen: Decimal | None = None

    @field_serializer(
        "max_stake_zen",
        "max_user_stake_per_market_zen",
        "max_market_stake_zen",
        "remaining_user_stake_zen",
        "remaining_market_stake_zen",
    )
    def _serialize_caps(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None


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


class ProofReceipt(BaseModel):
    request_id: str = Field(alias="requestId")
    market_id: int | None = Field(default=None, alias="marketId")
    event_id: str | None = Field(default=None, alias="eventId")
    condition_id: str | None = Field(default=None, alias="conditionId")
    market_address: str | None = Field(default=None, alias="marketAddress")
    proof_hash: str | None = Field(default=None, alias="proofHash")
    prover_version: str | None = Field(default=None, alias="proverVersion")
    circuit_hash: str | None = Field(default=None, alias="circuitHash")
    generated_at: datetime | None = Field(default=None, alias="generatedAt")
    proof: str | None = None
    public_signals: list[str] = Field(default_factory=list, alias="publicSignals")
    merkle_root: str | None = Field(default=None, alias="merkleRoot")
    total_escrow: str | None = Field(default=None, alias="totalEscrow")
    total_liability: str | None = Field(default=None, alias="totalLiability")
    rake_bps: int | None = Field(default=None, alias="rakeBps")
    winning_outcome_id: int | None = Field(default=None, alias="winningOutcomeId")
    pool_total_yes: str | None = Field(default=None, alias="poolTotalYes")
    pool_total_no: str | None = Field(default=None, alias="poolTotalNo")
    winning_pool: str | None = Field(default=None, alias="winningPool")
    total_pool: str | None = Field(default=None, alias="totalPool")

    model_config = ConfigDict(populate_by_name=True, validate_by_name=True)


class PricingQuoteRequest(BaseModel):
    stake_zen: Decimal = Field(..., gt=0)
    market_id: str = Field(..., description="Market ID for cap tracking")
    wallet_address: str = Field(..., description="User wallet to bind quote to (used for caps)")
    outcome_id: int = Field(..., ge=0, description="Outcome id to bind quote to")
    market_address: str | None = Field(default=None, description="Market contract address (auto-created when missing)")
    user_id: str | None = Field(
        default=None,
        description="(Deprecated) User identifier; defaults to wallet_address for cap tracking",
    )


class PricingQuoteResponse(BaseModel):
    stake_zen: Decimal
    stake_wei: int = 0
    zen_usd: Decimal
    zen_usd_scaled: int = 0
    payout_zen: Decimal
    fx_received_at: datetime | None = None
    fx_stale: bool = False
    displayed_odds_multiplier: Decimal
    rake_zen: Decimal
    refund_zen: Decimal
    hedge_usdc: Decimal
    haircut_percent: Decimal
    worsen_percent: Decimal
    rake_percent: Decimal
    total_monetization: Decimal
    chain_id: int = 0
    max_stake_zen: Decimal | None = None
    max_user_stake_per_market_zen: Decimal | None = None
    max_market_stake_zen: Decimal | None = None
    remaining_user_stake_zen: Decimal | None = None
    remaining_market_stake_zen: Decimal | None = None
    quote_id: str | None = None
    expires_at: datetime | None = None
    expiry_ts: int = 0
    signature: str | None = None
    signer: str | None = None
    market_id: str | None = None
    user_id: str | None = None
    wallet_address: str | None = None
    outcome_id: int | None = None
    market_address: str | None = None

    @field_serializer(
        "stake_zen",
        "zen_usd",
        "displayed_odds_multiplier",
        "rake_zen",
        "refund_zen",
        "hedge_usdc",
        "haircut_percent",
        "worsen_percent",
        "rake_percent",
        "total_monetization",
        "payout_zen",
        "max_stake_zen",
        "max_user_stake_per_market_zen",
        "max_market_stake_zen",
        "remaining_user_stake_zen",
        "remaining_market_stake_zen",
    )
    def _serialize_decimal(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None


class PricingQuotePayload(PricingQuoteResponse):
    model_config = ConfigDict(title="PricingQuotePayload")


class FxQuoteResponse(BaseModel):
    zen_usd: Decimal
    stale: bool = False
    received_at: datetime | None = None

    @field_serializer("zen_usd")
    def _serialize_fx(self, value: Decimal) -> float:
        return float(value)


class PricingSubmitRequest(BaseModel):
    quote: PricingQuotePayload
    max_fx_diff_percent: Decimal | None = Field(default=None, ge=0, description="Optional max FX drift percent vs live")


class PricingSubmitResponse(BaseModel):
    quote: PricingQuoteResponse
    current_fx: Decimal
    valid: bool = True


class TradeCommitRequest(BaseModel):
    quote_id: str = Field(..., description="Quote identifier to consume and commit")
    max_fx_diff_percent: Decimal | None = Field(
        default=None, description="Optional FX drift guard passed to pricing submit"
    )


class TradeCommitResponse(BaseModel):
    tx_hash: str
    quote_id: str
    market_id: str
    outcome_id: int
    stake_zen: float
    entry_fx: float
    potential_payout_zen: float | None = None
    protocol_topup_zen: float | None = None
    rake_zen: float | None = None
    status: str = "committed"
    ticket_id: int | None = None
    escrow_balance_wei: int | None = None
    salt: str | None = None
    relayer_status: str | None = None
    relayer_job_id: str | None = None


class PositionRecord(BaseModel):
    market_id: str
    market_title: str | None = None
    outcome_id: int
    stake_wei: int
    stake_zen: float
    tx_hash: str | None = None
    quote_id: str | None = None
    status: str = "committed"
    ticket_id: int | None = None
    created_at: datetime | None = None
    claimable: bool | None = None
    closes_at: datetime | None = None
    resolved_at: datetime | None = None
    proof_request_id: str | None = None
    merkle_root: str | None = None
    winning_outcome_id: int | None = None
    market_address: str | None = None
    resolution_status: str | None = None
    resolution_reason: str | None = None
    commits_blocked_at: datetime | None = None


class PositionsResponse(BaseModel):
    positions: list[PositionRecord]
    escrow_balance_wei: int | None = None


class CommitmentTicket(BaseModel):
    ticket_hash: str | None = Field(default=None, alias="ticketHash")
    leaf: str | None = None
    user: str | None = Field(default=None, alias="user_address")
    outcome_id: int | None = Field(default=None, alias="outcomeId")
    amount_wei: int | None = Field(default=None, alias="amount")
    salt: str | None = None
    leaf_index: int | None = Field(default=None, alias="merkleIndex")
    merkle_path: list[str] | None = Field(default=None, alias="merklePath")


class CommitmentsSyncRequest(BaseModel):
    market_id: str | None = None
    event_id: str | None = None
    tickets: list[CommitmentTicket]


class CommitmentsSyncResponse(BaseModel):
    recorded: int


class SettlementIngestRequest(BaseModel):
    market_id: str | None = None
    event_id: str | None = None
    merkle_root: str | None = Field(default=None, alias="merkleRoot")
    commitments_count: int | None = Field(default=None, alias="commitmentsCount")
    pool_total_yes: int | None = Field(default=None, alias="poolTotalYes")
    pool_total_no: int | None = Field(default=None, alias="poolTotalNo")
    total_escrow: int | None = Field(default=None, alias="totalEscrow")
    total_liability: int | None = Field(default=None, alias="totalLiability")
    rake_bps: int | None = Field(default=None, alias="rakeBps")
    winning_outcome_id: int | None = Field(default=None, alias="winningOutcomeId")
    proof_status: str | None = None
    proof_request_id: str | None = Field(default=None, alias="proofRequestId")
    proof_hash: str | None = Field(default=None, alias="proofHash")
    circuit_hash: str | None = Field(default=None, alias="circuitHash")


class SettlementIngestResponse(BaseModel):
    market_id: str
    updated: bool = True


class TradeStatusResponse(BaseModel):
    tx_hash: str
    status: str
    block_number: int | None = None
    gas_used: int | None = None
    effective_gas_price: int | None = None


class TradeClaimRequest(BaseModel):
    wallet_address: str
    market_id: str | None = None
    event_id: str | None = None
    ticket_id: int | None = None


class TradeClaimResponse(BaseModel):
    tx_hash: str
    market_id: str
    ticket_id: int
    outcome_id: int
    amount_wei: int
    status: str = "claimed"


class ClaimBundle(BaseModel):
    market_id: str = Field(alias="marketId")
    market_address: str = Field(alias="marketAddress")
    commitments_root: str = Field(alias="commitmentsRoot")
    ticket_id: int = Field(alias="ticketId")
    outcome_id: int = Field(alias="outcomeId")
    amount_wei: int = Field(alias="amountWei")
    salt: str | None
    merkle_proof: list[str] = Field(alias="merkleProof")
    leaf: str
    user: str


class ClaimBundlesResponse(BaseModel):
    bundles: list[ClaimBundle]


class QuoteRecord(BaseModel):
    quote_id: str = Field(alias="quoteId")
    status: str
    stake_zen: Decimal = Field(alias="stakeZen")
    stake_wei: int = Field(alias="stakeWei")
    fx_scaled: int = Field(alias="fxScaled")
    zen_usd: Decimal = Field(alias="zenUsd")
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
            level_dict = level.__dict__ if hasattr(level, "__dict__") else level
            if isinstance(level_dict, dict):
                price = ClobOrderBookResponse._coerce_decimal(level_dict.get("price"))
                size = ClobOrderBookResponse._coerce_decimal(level_dict.get("size"))
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
        except (ArithmeticError, ValueError, TypeError, InvalidOperation):
            return None


class TreasurySnapshot(BaseModel):
    id: int
    market_id: str
    outcome: str
    stake_zen: Decimal
    refund_zen: Decimal
    rake_zen: Decimal
    payout_profit_usdc: Decimal
    borrowed_usdc: Decimal
    lp_share_usdc: Decimal
    repay_amount_usdc: Decimal
    platform_usdc_revenue: Decimal
    zen_balance: Decimal
    usdc_balance: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer(
        "stake_zen",
        "refund_zen",
        "rake_zen",
        "payout_profit_usdc",
        "borrowed_usdc",
        "lp_share_usdc",
        "repay_amount_usdc",
        "platform_usdc_revenue",
        "zen_balance",
        "usdc_balance",
    )
    def _serialize_treasury_decimal(self, value: Decimal) -> float:
        return float(value)
