import importlib
import sys

from structlog import get_logger
from web3 import Web3

from .app import create_app
from .config import load_config
from .logging_setup import configure_logging
from .queue import TxQueue
from .security import RateLimiter
from .service import build_service

middleware_module = importlib.import_module("web3.middleware")
_poa_middleware = getattr(middleware_module, "geth_poa_middleware", None)
ExtraDataToPOAMiddleware = getattr(middleware_module, "ExtraDataToPOAMiddleware", None)

configure_logging()
logger = get_logger()

try:
    cfg = load_config()
except RuntimeError as err:
    print(f"Failed to load config: {err}", file=sys.stderr)
    raise

web3 = Web3(Web3.HTTPProvider(cfg.rpc_url, request_kwargs={"timeout": cfg.http_timeout_seconds}))
if _poa_middleware is not None:
    web3.middleware_onion.inject(_poa_middleware, layer=0)
elif ExtraDataToPOAMiddleware is not None:
    web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
account = web3.eth.account.from_key(cfg.relayer_private_key)
service = build_service(
    web3,
    Web3.to_checksum_address(cfg.relayer_escrow_address),
    account,
    cfg.chain_id,
    cfg.rpc_url,
    max_retries=cfg.max_retries,
    retry_backoff_seconds=cfg.retry_backoff_seconds,
    tx_timeout_seconds=cfg.tx_timeout_seconds,
    max_block_age_seconds=cfg.max_block_age_seconds,
    min_relayer_balance_wei=cfg.min_relayer_balance_wei,
    min_escrow_token_balance_wei=cfg.min_escrow_token_balance_wei,
    min_relayer_token_allowance_wei=cfg.min_relayer_token_allowance_wei,
    fee_bump_percent=cfg.fee_bump_percent,
    preflight_mode=cfg.preflight_mode,
    api_base_url=cfg.api_base_url,
    api_bearer_token=cfg.api_bearer_token,
    api_internal_secret=cfg.api_internal_secret,
    api_timeout_seconds=cfg.api_timeout_seconds,
)
service.health_deep_cache_ttl_seconds = cfg.health_deep_cache_ttl_seconds

queue = TxQueue(
    cfg.queue_db_path,
    service,
    dsn=cfg.queue_dsn,
    poll_seconds=cfg.queue_poll_seconds,
    max_attempts=cfg.queue_max_attempts,
    fee_bump_percent=cfg.fee_bump_percent,
)

rate_limiter = None
if cfg.rate_limit_requests > 0:
    rate_limiter = RateLimiter(cfg.rate_limit_requests, cfg.rate_limit_window_seconds)

logger.info(
    "relayer_boot",
    chain_id=cfg.chain_id,
    rpc_url=cfg.rpc_url,
    relayer_address=account.address,
    escrow_address=cfg.relayer_escrow_address,
    host=cfg.host,
    port=cfg.port,
    queue_db=cfg.queue_db_path,
    queue_dsn=cfg.queue_dsn,
    http_timeout_seconds=cfg.http_timeout_seconds,
)

app = create_app(
    service,
    cfg.chain_id,
    cfg.rpc_url,
    bearer_token=cfg.bearer_token,
    tx_queue=queue,
    rate_limiter=rate_limiter,
    ip_allowlist=cfg.ip_allowlist,
    trust_x_forwarded_for=cfg.trust_x_forwarded_for,
)
