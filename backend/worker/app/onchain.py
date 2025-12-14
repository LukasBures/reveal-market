from __future__ import annotations

import asyncio
import logging
import threading
import time

from shared.logging import log_event
from shared.onchain import (
    MARKET_FACTORY_ABI,
    OnChainConfigurationError,
    get_async_web3,
    load_account,
    to_checksum,
)

logger = logging.getLogger("reveal_market.worker")
DEPLOY_LOCK = threading.Lock()


async def get_next_market_id(rpc_url: str, factory_address: str) -> int:
    """Return the next market id from the factory."""

    web3 = get_async_web3(rpc_url)
    factory = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    return await factory.functions.nextMarketId().call()


async def predict_market_address(rpc_url: str, factory_address: str, market_id: int) -> str:
    """Predict the deterministic market clone address for a given market id."""

    web3 = get_async_web3(rpc_url)
    factory = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    return await factory.functions.predictMarketAddress(market_id).call()


async def _send_create_market_transaction(
    *,
    rpc_url: str,
    factory_address: str,
    private_key: str,
    event_id: str,
    commit_deadline: int,
    reveal_deadline: int,
    oracle: str,
    collateral: str | None,
    gas_price_wei: int | None,
    max_priority_fee_wei: int | None,
    max_retries: int,
) -> tuple[str, int | None]:
    from web3.exceptions import ContractLogicError, TransactionNotFound

    web3 = get_async_web3(rpc_url)
    account = load_account(private_key)
    factory = web3.eth.contract(address=to_checksum(factory_address), abi=MARKET_FACTORY_ABI)
    oracle_checksum = to_checksum(oracle)
    collateral_checksum = (
        to_checksum(collateral)
        if collateral
        else web3.to_checksum_address("0x0000000000000000000000000000000000000000")
    )

    try:
        from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive
        raise OnChainConfigurationError("tenacity is required for on-chain retries") from exc

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((ContractLogicError, TransactionNotFound, ValueError)),
        reraise=True,
    ):
        with attempt:
            nonce = await web3.eth.get_transaction_count(account.address)
            chain_id = await web3.eth.chain_id
            tx_params = {
                "from": account.address,
                "nonce": nonce,
                "chainId": chain_id,
                "value": 0,
            }

            if gas_price_wei is not None and max_priority_fee_wei is None:
                tx_params.update({"gasPrice": gas_price_wei})
            else:
                if max_priority_fee_wei is None:
                    priority_fee = await web3.eth.max_priority_fee
                else:
                    priority_fee = max_priority_fee_wei
                base_fee = await web3.eth.gas_price
                tx_params.update(
                    {
                        "maxPriorityFeePerGas": priority_fee,
                        "maxFeePerGas": (gas_price_wei if gas_price_wei is not None else base_fee + priority_fee),
                    }
                )

            create_fn = factory.functions.createMarket(
                event_id,
                commit_deadline,
                reveal_deadline,
                oracle_checksum,
                collateral_checksum,
                0,
            )
            estimate_kwargs = dict(tx_params)
            gas_estimate = await create_fn.estimate_gas(estimate_kwargs)
            tx_params["gas"] = int(gas_estimate * 1.2)
            transaction = await create_fn.build_transaction(tx_params)

            signed_tx = account.sign_transaction(transaction)
            tx_hash = await web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            log_event(
                logger,
                logging.INFO,
                "worker.tx.submitted",
                "submitted createMarket transaction",
                tx_hash=tx_hash.hex(),
                event_id=event_id,
            )
            receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
            logs = factory.events.MarketCreated().process_receipt(receipt)
            if not logs:
                raise TransactionNotFound("MarketCreated event missing from receipt")
            market_address = logs[0]["args"]["market"]
            market_id = logs[0]["args"].get("marketId")
            log_event(
                logger,
                logging.INFO,
                "worker.tx.mined",
                "createMarket transaction mined",
                tx_hash=tx_hash.hex(),
                market_address=market_address,
                block_number=receipt.blockNumber,
                market_id=market_id,
            )
            return market_address, market_id

    raise RuntimeError("Exceeded max retries for createMarket")

