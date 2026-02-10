from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

EXPOSURE_GAUGE = Gauge(
    "hedger_market_exposure_usd",
    "USD exposure per market outcome after FX haircut.",
    ["market_id", "outcome"],
)
NET_EXPOSURE_GAUGE = Gauge(
    "hedger_market_net_exposure_usd",
    "Net USD exposure (YES minus NO) per market.",
    ["market_id"],
)
COVERAGE_RATIO_GAUGE = Gauge(
    "hedger_coverage_ratio",
    "Hedging coverage ratio by market.",
    ["market_id"],
)
LP_UTILIZATION_GAUGE = Gauge(
    "hedger_lp_vault_utilization_ratio",
    "Utilized USDC / total LP vault capacity.",
)
FLOAT_BALANCE_GAUGE = Gauge(
    "hedger_float_balance_zen",
    "Available ZEN float for payouts on Horizen.",
)
PNL_UNREALIZED_GAUGE = Gauge(
    "hedger_unrealized_pnl_usd",
    "Unrealized PnL across hedging positions, in USD.",
)
PNL_REALIZED_GAUGE = Gauge(
    "hedger_realized_pnl_usd",
    "Realized PnL across hedging positions, in USD.",
)
RISK_BREACH_COUNTER = Counter(
    "hedger_risk_breaches_total",
    "Risk limit breaches by category.",
    ["code", "severity"],
)
EVENT_LAG_GAUGE = Gauge(
    "hedger_event_listener_lag_seconds",
    "Delay between the latest on-chain commit and hedger ingestion.",
)
SETTLEMENT_LATENCY_GAUGE = Histogram(
    "hedger_settlement_latency_seconds",
    "Latency from settlement trigger to prover submission.",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)
PROVER_LATENCY_HISTOGRAM = Histogram(
    "hedger_prover_roundtrip_seconds",
    "Round-trip latency (seconds) to generate and submit settlement proofs.",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300, 600),
)
HEDGE_EXECUTIONS = Counter(
    "hedger_hedge_executions_total",
    "Hedge executions grouped by action and outcome.",
    ["action", "outcome"],
)
HEDGE_DECISIONS = Counter(
    "hedger_hedge_decisions_total",
    "Hedge decisions grouped by action and reason.",
    ["action", "reason"],
)


def update_exposure_metrics(market_id: str, yes_usd: float, no_usd: float, coverage_ratio: float | None = None) -> None:
    """Publish exposure gauges for a single market."""

    EXPOSURE_GAUGE.labels(market_id=market_id, outcome="yes").set(yes_usd)
    EXPOSURE_GAUGE.labels(market_id=market_id, outcome="no").set(no_usd)
    NET_EXPOSURE_GAUGE.labels(market_id=market_id).set(yes_usd - no_usd)
    if coverage_ratio is not None:
        COVERAGE_RATIO_GAUGE.labels(market_id=market_id).set(coverage_ratio)


def record_risk_breach(code: str, severity: str) -> None:
    """Increment counters when a risk rule is triggered."""

    RISK_BREACH_COUNTER.labels(code=code, severity=severity).inc()


def update_float_and_utilization(float_zen: float | None, lp_utilization: float | None) -> None:
    if float_zen is not None:
        FLOAT_BALANCE_GAUGE.set(float_zen)
    if lp_utilization is not None:
        LP_UTILIZATION_GAUGE.set(lp_utilization)


def record_event_lag(seconds: float) -> None:
    EVENT_LAG_GAUGE.set(seconds)


def record_pnl(realized_usd: float | None = None, unrealized_usd: float | None = None) -> None:
    if realized_usd is not None:
        PNL_REALIZED_GAUGE.set(realized_usd)
    if unrealized_usd is not None:
        PNL_UNREALIZED_GAUGE.set(unrealized_usd)


def record_hedge_decision(action: str, reason: str) -> None:
    HEDGE_DECISIONS.labels(action=action, reason=reason).inc()


def record_settlement_latency(seconds: float) -> None:
    SETTLEMENT_LATENCY_GAUGE.observe(seconds)
