from prometheus_client import Counter, Histogram

REQUEST_LATENCY = Histogram(
    "api_request_latency_seconds",
    "Latency of HTTP requests",
    ["method", "path", "status_code"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
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
