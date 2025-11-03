from __future__ import annotations

import logging
from typing import List

from shared.logging import log_event
from shared.onchain import MARKET_FACTORY_ABI, OnChainConfigurationError, get_async_web3, to_checksum

from .config import get_settings, Settings

logger = logging.getLogger("reveal_market.api")


async def fetch_factory_markets(settings: Settings) -> List[str]:
    rpc_url = settings.rpc_url and str(settings.rpc_url)
    factory_address = settings.factory_address
    if not (rpc_url and factory_address):
        raise OnChainConfigurationError("Factory RPC configuration missing")

    web3 = get_async_web3(rpc_url)
    contract = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    addresses = await contract.functions.getMarkets().call()
    log_event(
        logger,
        logging.DEBUG,
        "api.onchain.get_markets",
        "fetched factory market addresses",
        count=len(addresses),
    )
    return addresses
