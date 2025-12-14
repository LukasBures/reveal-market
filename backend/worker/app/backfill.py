from __future__ import annotations

from typing import Any

from shared.logging import get_logger
from shared.onchain import get_async_web3, to_checksum
from shared.onchain.abi import MARKET_FACTORY_ABI
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def backfill_market_addresses(
    session: AsyncSession,
    *,
    rpc_url: str,
    factory_address: str,
    get_markets_missing_address: Any,
) -> int:
    """Populate market_address for markets missing it by querying the factory."""

    web3 = get_async_web3(rpc_url)
    factory = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    count = 0
    markets = await get_markets_missing_address(session)
    for market in markets:
        try:
            address = await factory.functions.marketAddress(int(market.onchain_market_id or 0)).call()
            market.market_address = address
            session.add(market)
            await session.flush()
            count += 1
            logger.info("backfill.market_address.updated", extra={"market_id": market.event_id, "address": address})
        except Exception as exc:
            logger.warning(
                "backfill.market_address.failed",
                extra={"market_id": market.event_id, "onchain_id": market.onchain_market_id, "error": str(exc)},
            )
            continue
    return count
