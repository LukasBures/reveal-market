from prometheus_client import Counter, Gauge, Histogram

ACTIVE_REQUESTS = Gauge(
    "api_active_requests",
    "Number of in-flight HTTP requests currently being processed",
)

REQUEST_LATENCY = Histogram(
    "api_request_latency_seconds",
    "Latency of HTTP requests",
    ["method", "path", "status_code"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

DB_QUERY_COUNT = Histogram(
    "api_db_query_count",
    "DB queries per request",
    buckets=(1, 5, 10, 25, 50, 100, 200, 400),
)

DB_QUERY_TIME_MS = Histogram(
    "api_db_query_time_ms",
    "Total DB time per request (ms)",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000),
)

DB_QUERY_MAX_MS = Histogram(
    "api_db_query_max_ms",
    "Slowest single DB query per request (ms)",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000),
)

CACHE_REQUESTS = Counter(
    "api_cache_requests_total",
    "Cache hits/misses by source",
    ["source", "outcome"],
)

MARKETS_CACHE_COUNTER = Counter(
    "markets_cache_requests_total",
    "Cache hits and misses for /markets",
    ["outcome", "status", "category"],
)
PRICING_COUNTER = Counter(
    "pricing_quote_events_total",
    "Pricing quote lifecycle events",
    ["event", "result"],
)
MARKET_DETAIL_CACHE_COUNTER = Counter(
    "markets_detail_cache_requests_total",
    "Cache hits and misses for /markets/{event_id}",
    ["outcome"],
)
RESOLUTION_CACHE_COUNTER = Counter(
    "markets_resolution_cache_requests_total",
    "Cache hits and misses for /resolution/{condition_id}",
    ["outcome"],
)
