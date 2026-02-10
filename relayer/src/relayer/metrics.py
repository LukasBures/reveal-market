from prometheus_client import Counter, Gauge, Histogram

REQUEST_LATENCY = Histogram(
    "relayer_request_latency_seconds",
    "HTTP request latency in seconds",
    labelnames=["endpoint", "status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

TX_LATENCY = Histogram(
    "relayer_tx_latency_seconds",
    "Transaction latency from submission to receipt",
    labelnames=["action"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160),
)

TX_OUTCOMES = Counter(
    "relayer_tx_outcomes_total",
    "Transaction outcomes by action",
    labelnames=["action", "outcome"],
)

HEALTH_CHECKS = Counter(
    "relayer_health_checks_total",
    "Health check calls by status",
    labelnames=["status"],
)

RPC_ERRORS = Counter(
    "relayer_rpc_errors_total",
    "RPC errors by label and error type",
    labelnames=["label", "error_type"],
)

RPC_CIRCUIT_STATE = Gauge(
    "relayer_rpc_circuit_open",
    "RPC circuit breaker open flag (1=open,0=closed)",
)

CHAIN_HEAD_LAG_SECONDS = Gauge(
    "relayer_chain_head_lag_seconds",
    "Seconds behind latest known chain head (based on block timestamp)",
)

FEE_BUMP_FACTOR = Gauge(
    "relayer_fee_bump_factor",
    "Current fee bump factor applied by the queue",
)

QUEUE_ERROR_REASONS = Counter(
    "relayer_queue_error_reasons_total",
    "Queue error reason aggregation by action",
    labelnames=["action", "reason"],
)

QUEUE_OUTCOMES = Counter(
    "relayer_queue_outcomes_total",
    "Queue outcomes by action and status",
    labelnames=["action", "status"],
)

QUEUE_DEPTH = Gauge(
    "relayer_queue_depth",
    "Number of pending/running queue jobs",
)

QUEUE_DEADLETTER_DEPTH = Gauge(
    "relayer_queue_deadletter_depth",
    "Number of deadletter queue jobs",
)

QUEUE_DEADLETTER_TOTAL = Counter(
    "relayer_queue_deadletter_total",
    "Total number of jobs moved to the deadletter queue",
    labelnames=["action"],
)

QUEUE_OLDEST_BACKLOG_AGE_SECONDS = Gauge(
    "relayer_queue_oldest_backlog_age_seconds",
    "Age in seconds of the oldest pending/running queue job",
)
