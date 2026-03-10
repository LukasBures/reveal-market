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
FLOAT_BALANCE_GAUGE = Gauge(
    "hedger_float_balance_zen",
    "Available ZEN float for payouts on Horizen.",
)
HOT_WALLET_BALANCE_GAUGE = Gauge(
    "hedger_hot_wallet_usdc_balance",
    "USDC.e balance in the hedger hot wallet.",
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


def remove_exposure_metrics(market_id: str) -> None:
    """Remove per-market gauge labels after finalization to prevent cardinality leak."""

    EXPOSURE_GAUGE.remove(market_id, "yes")
    EXPOSURE_GAUGE.remove(market_id, "no")
    NET_EXPOSURE_GAUGE.remove(market_id)
    COVERAGE_RATIO_GAUGE.remove(market_id)


def record_risk_breach(code: str, severity: str) -> None:
    """Increment counters when a risk rule is triggered."""

    RISK_BREACH_COUNTER.labels(code=code, severity=severity).inc()


def update_hot_wallet_balance(balance_usdc: float | None) -> None:
    if balance_usdc is not None:
        HOT_WALLET_BALANCE_GAUGE.set(balance_usdc)


def record_event_lag(seconds: float) -> None:
    EVENT_LAG_GAUGE.set(seconds)


def record_hedge_decision(action: str, reason: str) -> None:
    HEDGE_DECISIONS.labels(action=action, reason=reason).inc()


def record_settlement_latency(seconds: float) -> None:
    SETTLEMENT_LATENCY_GAUGE.observe(seconds)
