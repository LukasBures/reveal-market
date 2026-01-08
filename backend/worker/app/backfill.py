from __future__ import annotations

from typing import Any, cast

from shared.logging import get_logger
from shared.onchain import get_async_web3, to_checksum
from shared.onchain.abi import MARKET_FACTORY_ABI, REVEAL_MARKET_ABI
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def backfill_market_addresses(
    session: AsyncSession,
    *,
    rpc_url: str,
    factory_address: str,
    get_markets_missing_address: Any,
    limit: int | None = None,
) -> int:
    """Populate market_address for markets missing it by querying the factory."""

    if limit is not None and limit <= 0:
        return 0
    web3 = get_async_web3(rpc_url)
    factory = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    count = 0
    skipped_missing_id = 0
    markets = await get_markets_missing_address(session, limit=limit)
    for market in markets:
        onchain_id = getattr(market, "onchain_market_id", None)
        if onchain_id in (None, 0):
            skipped_missing_id += 1
            continue
        try:
            onchain_id_int = int(cast(int | str, onchain_id))
            address = await factory.functions.marketAddress(onchain_id_int).call()
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
    if skipped_missing_id:
        logger.info(
            "backfill.market_address.skipped",
            extra={"reason": "missing_onchain_id", "count": skipped_missing_id},
        )
    return count


async def backfill_market_params(
    session: AsyncSession,
    *,
    rpc_url: str,
    factory_address: str,
    get_markets_for_sync: Any,
    limit: int | None = None,
) -> int:
    """Populate on-chain factory params (rake, ids, factory) for markets missing them."""

    if limit is not None and limit <= 0:
        return 0
    web3 = get_async_web3(rpc_url)
    factory = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    count = 0
    skipped_missing_id = 0
    markets = await get_markets_for_sync(session, limit=limit)
    for market in markets:
        onchain_id = getattr(market, "onchain_market_id", None)
        market_address = getattr(market, "market_address", None)
        if onchain_id is None and market_address:
            try:
                contract = web3.eth.contract(address=to_checksum(market_address), abi=REVEAL_MARKET_ABI)
                onchain_id = int(await contract.functions.marketId().call())
            except Exception as exc:
                logger.warning(
                    "backfill.market_params.market_id_failed",
                    extra={"market_id": market.event_id, "address": market_address, "error": str(exc)},
                )
                continue
        if onchain_id is None:
            skipped_missing_id += 1
            continue
        try:
            params = await factory.functions.getMarketParams(int(onchain_id)).call()
        except Exception as exc:
            logger.warning(
                "backfill.market_params.failed",
                extra={"market_id": market.event_id, "onchain_id": onchain_id, "error": str(exc)},
            )
            continue
        onchain_address = params[0]
        rake_bps = int(params[9])
        updated = False
        if onchain_address and market.market_address:
            if str(onchain_address).lower() != str(market.market_address).lower():
                logger.warning(
                    "backfill.market_params.address_mismatch",
                    extra={
                        "market_id": market.event_id,
                        "db_address": market.market_address,
                        "onchain_address": onchain_address,
                    },
                )
            else:
                market.market_address = onchain_address
                updated = True
        elif onchain_address and not market.market_address:
            market.market_address = onchain_address
            updated = True
        if market.onchain_market_id is None:
            market.onchain_market_id = int(onchain_id)
            updated = True
        if market.factory is None or market.factory == "":
            market.factory = factory_address
            updated = True
        if market.rake_bps != rake_bps:
            market.rake_bps = rake_bps
            updated = True
        if updated:
            session.add(market)
            await session.flush()
            count += 1
            logger.info(
                "backfill.market_params.updated",
                extra={
                    "market_id": market.event_id,
                    "onchain_id": onchain_id,
                    "rake_bps": rake_bps,
                },
            )
    if skipped_missing_id:
        logger.warning(
            "backfill.market_params.skipped",
            extra={"reason": "missing_onchain_id", "count": skipped_missing_id},
        )
    return count
