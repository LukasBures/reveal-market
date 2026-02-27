import ipaddress
import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_config_logger = logging.getLogger("reveal_market.relayer.config")

IPAllowEntry = ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network

# Env vars that should use the RM_ prefix for cross-service consistency.
_RM_PREFIX_VARS = {"RPC_URL", "CHAIN_ID"}


def _env_with_prefix(name: str) -> str | None:
    """Read an env var, preferring RM_ prefix. Warn if only the legacy name is set."""
    if name in _RM_PREFIX_VARS:
        rm_name = f"RM_{name}"
        rm_val = os.getenv(rm_name)
        legacy_val = os.getenv(name)
        if rm_val:
            return rm_val
        if legacy_val:
            _config_logger.warning(
                "deprecated env var %s; use %s instead",
                name,
                rm_name,
            )
            return legacy_val
        return None
    return os.getenv(name)


def _require_env(name: str) -> str:
    val = _env_with_prefix(name)
    if not val:
        raise RuntimeError(f"Missing env var: {name}")
    return val


def _int_env(name: str, default: int) -> int:
    val = _env_with_prefix(name)
    return int(val) if val else default


def _float_env(name: str, default: float) -> float:
    val = _env_with_prefix(name)
    return float(val) if val else default


def _bool_env(name: str, default: bool = False) -> bool:
    val = _env_with_prefix(name)
    if val is None:
        return default
    normalized = val.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise RuntimeError(f"Invalid boolean for {name}: {val}")


def _queue_dsn() -> str | None:
    dsn = os.getenv("RM_DATABASE_URL")
    if dsn and dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn.split("postgresql+psycopg2://", 1)[1]
    return dsn


def _preflight_mode() -> str:
    mode = (os.getenv("RELAYER_PREFLIGHT_MODE") or "none").strip().lower()
    if mode in ("", "none", "off", "false", "0"):
        return "none"
    if mode in ("true", "1", "yes"):
        return "both"
    if mode in ("call", "estimate", "both"):
        return mode
    raise RuntimeError(f"Invalid RELAYER_PREFLIGHT_MODE: {mode}")


def _ip_allowlist() -> list[IPAllowEntry]:
    raw = os.getenv("RELAYER_IP_ALLOWLIST")
    if not raw:
        return []
    entries: list[IPAllowEntry] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            if "/" in value:
                entries.append(ipaddress.ip_network(value, strict=False))
            else:
                entries.append(ipaddress.ip_address(value))
        except ValueError as err:
            raise RuntimeError(f"Invalid RELAYER_IP_ALLOWLIST entry: {value}") from err
    return entries


def _proxy_allowlist() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.getenv("RELAYER_TRUSTED_PROXY_CIDRS")
    if not raw:
        return []
    entries: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            entries.append(ipaddress.ip_network(value, strict=False))
        except ValueError as err:
            raise RuntimeError(f"Invalid RELAYER_TRUSTED_PROXY_CIDRS entry: {value}") from err
    return entries


@dataclass
class RelayerConfig:
    rpc_url: str
    chain_id: int
    relayer_private_key: str
    relayer_escrow_address: str
    host: str
    port: int
    bearer_token: str | None
    allow_insecure_auth: bool
    max_block_age_seconds: int
    min_relayer_balance_wei: int
    max_retries: int
    retry_backoff_seconds: float
    tx_timeout_seconds: int
    queue_db_path: str
    queue_dsn: str | None
    queue_poll_seconds: float
    queue_max_attempts: int
    queue_max_payload_bytes: int
    queue_running_ttl_seconds: int
    fee_bump_percent: float
    min_escrow_token_balance_wei: int
    min_relayer_token_allowance_wei: int
    http_timeout_seconds: int
    preflight_mode: str
    rate_limit_requests: int
    rate_limit_window_seconds: int
    ip_allowlist: list[IPAllowEntry]
    trust_x_forwarded_for: bool
    trusted_proxy_cidrs: list[ipaddress.IPv4Network | ipaddress.IPv6Network]
    api_base_url: str | None
    api_bearer_token: str | None
    api_internal_secret: str | None
    api_timeout_seconds: int
    health_deep_cache_ttl_seconds: int
    api_client_max_age_seconds: int
    api_health_failure_cooldown_seconds: int
    rpc_circuit_breaker_threshold: int
    rpc_circuit_breaker_window_seconds: float
    rpc_circuit_breaker_cooldown_seconds: float


def load_config() -> RelayerConfig:
    bearer_token = os.getenv("RELAYER_BEARER_TOKEN")
    allow_insecure_auth = _bool_env("RELAYER_ALLOW_INSECURE_AUTH", False)
    if not bearer_token and not allow_insecure_auth:
        raise RuntimeError("RELAYER_BEARER_TOKEN is required unless RELAYER_ALLOW_INSECURE_AUTH=true")
    tx_timeout_seconds = _int_env("RELAYER_TX_TIMEOUT_SECONDS", 120)
    rate_limit_requests = _int_env("RELAYER_RATE_LIMIT_REQUESTS", 30)
    rate_limit_window_seconds = _int_env("RELAYER_RATE_LIMIT_WINDOW_SECONDS", 60)
    queue_max_payload_bytes = _int_env("RELAYER_QUEUE_MAX_PAYLOAD_BYTES", 131072)
    queue_running_ttl_env = os.getenv("RELAYER_QUEUE_RUNNING_TTL_SECONDS")
    if queue_running_ttl_env is None:
        queue_running_ttl_seconds = tx_timeout_seconds + 30
    else:
        queue_running_ttl_seconds = int(queue_running_ttl_env)
    if rate_limit_requests < 0:
        raise RuntimeError("RELAYER_RATE_LIMIT_REQUESTS must be >= 0")
    if rate_limit_requests > 0 and rate_limit_window_seconds <= 0:
        raise RuntimeError("RELAYER_RATE_LIMIT_WINDOW_SECONDS must be > 0 when rate limiting is enabled")
    if queue_max_payload_bytes <= 0:
        raise RuntimeError("RELAYER_QUEUE_MAX_PAYLOAD_BYTES must be > 0")
    if queue_running_ttl_seconds <= 0:
        raise RuntimeError("RELAYER_QUEUE_RUNNING_TTL_SECONDS must be > 0")

    return RelayerConfig(
        rpc_url=_require_env("RPC_URL"),
        chain_id=int(_require_env("CHAIN_ID")),
        relayer_private_key=_require_env("RELAYER_PRIVATE_KEY"),
        relayer_escrow_address=_require_env("RELAYER_ESCROW_ADDRESS"),
        host=_require_env("RELAYER_HOST"),
        port=int(_require_env("RELAYER_PORT")),
        bearer_token=bearer_token,
        allow_insecure_auth=allow_insecure_auth,
        max_block_age_seconds=_int_env("RELAYER_MAX_BLOCK_AGE_SECONDS", 60),
        min_relayer_balance_wei=_int_env("RELAYER_MIN_BALANCE_WEI", 0),
        max_retries=_int_env("RELAYER_MAX_RETRIES", 3),
        retry_backoff_seconds=_float_env("RELAYER_RETRY_BACKOFF_SECONDS", 0.5),
        tx_timeout_seconds=tx_timeout_seconds,
        queue_db_path=os.getenv("RELAYER_QUEUE_DB_PATH", "relayer_queue.db"),
        queue_dsn=_queue_dsn(),
        queue_poll_seconds=_float_env("RELAYER_QUEUE_POLL_SECONDS", 1.0),
        queue_max_attempts=_int_env("RELAYER_QUEUE_MAX_ATTEMPTS", 5),
        queue_max_payload_bytes=queue_max_payload_bytes,
        queue_running_ttl_seconds=queue_running_ttl_seconds,
        fee_bump_percent=_float_env("RELAYER_FEE_BUMP_PERCENT", 0.15),
        min_escrow_token_balance_wei=_int_env("RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI", 0),
        min_relayer_token_allowance_wei=_int_env("RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI", 0),
        http_timeout_seconds=_int_env("RELAYER_HTTP_TIMEOUT_SECONDS", 10),
        preflight_mode=_preflight_mode(),
        rate_limit_requests=rate_limit_requests,
        rate_limit_window_seconds=rate_limit_window_seconds,
        ip_allowlist=_ip_allowlist(),
        trust_x_forwarded_for=_bool_env("RELAYER_TRUST_X_FORWARDED_FOR", False),
        trusted_proxy_cidrs=_proxy_allowlist(),
        api_base_url=os.getenv("RELAYER_API_BASE_URL"),
        api_bearer_token=os.getenv("RELAYER_API_BEARER_TOKEN"),
        api_internal_secret=os.getenv("RELAYER_API_INTERNAL_SECRET"),
        api_timeout_seconds=_int_env("RELAYER_API_TIMEOUT_SECONDS", 10),
        health_deep_cache_ttl_seconds=_int_env("RELAYER_HEALTH_DEEP_CACHE_TTL_SECONDS", 10),
        api_client_max_age_seconds=_int_env("RELAYER_API_CLIENT_MAX_AGE_SECONDS", 900),
        api_health_failure_cooldown_seconds=_int_env("RELAYER_API_HEALTH_COOLDOWN_SECONDS", 15),
        rpc_circuit_breaker_threshold=_int_env("RELAYER_RPC_CIRCUIT_THRESHOLD", 5),
        rpc_circuit_breaker_window_seconds=_float_env("RELAYER_RPC_CIRCUIT_WINDOW_SECONDS", 30.0),
        rpc_circuit_breaker_cooldown_seconds=_float_env("RELAYER_RPC_CIRCUIT_COOLDOWN_SECONDS", 30.0),
    )
