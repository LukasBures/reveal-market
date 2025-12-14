import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing env var: {name}")
    return val


def _int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _float_env(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _queue_dsn() -> str | None:
    dsn = os.getenv("RM_DATABASE_URL")
    if dsn and dsn.startswith("postgresql+psycopg2://"):
        dsn = "postgresql://" + dsn.split("postgresql+psycopg2://", 1)[1]
    return dsn


@dataclass
class RelayerConfig:
    rpc_url: str
    chain_id: int
    relayer_private_key: str
    relayer_escrow_address: str
    host: str
    port: int
    bearer_token: str | None
    max_block_age_seconds: int
    min_relayer_balance_wei: int
    max_retries: int
    retry_backoff_seconds: float
    tx_timeout_seconds: int
    queue_db_path: str
    queue_dsn: str | None
    queue_poll_seconds: float
    queue_max_attempts: int
    fee_bump_percent: float
    min_escrow_token_balance_wei: int
    min_relayer_token_allowance_wei: int
    http_timeout_seconds: int
    api_base_url: str | None
    api_bearer_token: str | None
    api_timeout_seconds: int


def load_config() -> RelayerConfig:
    return RelayerConfig(
        rpc_url=_require_env("RPC_URL"),
        chain_id=int(_require_env("CHAIN_ID")),
        relayer_private_key=_require_env("RELAYER_PRIVATE_KEY"),
        relayer_escrow_address=_require_env("RELAYER_ESCROW_ADDRESS"),
        host=_require_env("RELAYER_HOST"),
        port=int(_require_env("RELAYER_PORT")),
        bearer_token=os.getenv("RELAYER_BEARER_TOKEN"),
        max_block_age_seconds=_int_env("RELAYER_MAX_BLOCK_AGE_SECONDS", 60),
        min_relayer_balance_wei=_int_env("RELAYER_MIN_BALANCE_WEI", 0),
        max_retries=_int_env("RELAYER_MAX_RETRIES", 3),
        retry_backoff_seconds=_float_env("RELAYER_RETRY_BACKOFF_SECONDS", 0.5),
        tx_timeout_seconds=_int_env("RELAYER_TX_TIMEOUT_SECONDS", 120),
        queue_db_path=os.getenv("RELAYER_QUEUE_DB_PATH", "relayer_queue.db"),
        queue_dsn=_queue_dsn(),
        queue_poll_seconds=_float_env("RELAYER_QUEUE_POLL_SECONDS", 1.0),
        queue_max_attempts=_int_env("RELAYER_QUEUE_MAX_ATTEMPTS", 5),
        fee_bump_percent=_float_env("RELAYER_FEE_BUMP_PERCENT", 0.15),
        min_escrow_token_balance_wei=_int_env("RELAYER_MIN_ESCROW_TOKEN_BALANCE_WEI", 0),
        min_relayer_token_allowance_wei=_int_env("RELAYER_MIN_RELAYER_TOKEN_ALLOWANCE_WEI", 0),
        http_timeout_seconds=_int_env("RELAYER_HTTP_TIMEOUT_SECONDS", 10),
        api_base_url=os.getenv("RELAYER_API_BASE_URL"),
        api_bearer_token=os.getenv("RELAYER_API_BEARER_TOKEN"),
        api_timeout_seconds=_int_env("RELAYER_API_TIMEOUT_SECONDS", 10),
    )
