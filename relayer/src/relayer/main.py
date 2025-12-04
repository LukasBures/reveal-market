import sys

from web3 import Web3
from web3.middleware import geth_poa_middleware

from .app import create_app
from .config import load_config
from .logging_setup import configure_logging
from .service import build_service

configure_logging()

try:
    cfg = load_config()
except RuntimeError as err:
    print(f"Failed to load config: {err}", file=sys.stderr)
    raise

web3 = Web3(Web3.HTTPProvider(cfg.rpc_url))
web3.middleware_onion.inject(geth_poa_middleware, layer=0)
account = web3.eth.account.from_key(cfg.relayer_private_key)
service = build_service(web3, Web3.to_checksum_address(cfg.relayer_escrow_address), account, cfg.chain_id)

app = create_app(service, cfg.chain_id, cfg.rpc_url)
