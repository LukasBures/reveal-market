from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from shared.logging import log_event
from shared.onchain import MARKET_FACTORY_ABI, OnChainConfigurationError, get_async_web3, load_account, to_checksum

logger = logging.getLogger("reveal_market.worker")


class OnChainDisabled(Exception):
    """Raised when on-chain execution is intentionally disabled."""


async def _send_create_market_transaction(
    *,
    rpc_url: str,
    factory_address: str,
    private_key: str,
    event_id: str,
    commit_deadline: int,
    reveal_deadline: int,
    oracle: str,
    collateral: Optional[str],
    gas_price_wei: Optional[int],
    max_priority_fee_wei: Optional[int],
    max_retries: int,
) -> str:
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
            log_event(
                logger,
                logging.INFO,
                "worker.tx.mined",
                "createMarket transaction mined",
                tx_hash=tx_hash.hex(),
                market_address=market_address,
                block_number=receipt.blockNumber,
            )
            return market_address

    raise RuntimeError("Exceeded max retries for createMarket")


def maybe_create_onchain_market(settings, market, session) -> Optional[str]:
    if not settings.auto_create_onchain_markets:
        return None

    try:
        rpc_url = settings.rpc_url and str(settings.rpc_url)
        factory_address = settings.factory_address
        account_secret = settings.wallet_private_key.get_secret_value() if settings.wallet_private_key else None
    except AttributeError:
        rpc_url = None
        factory_address = None
        account_secret = None

    if not (rpc_url and factory_address and account_secret):
        log_event(
            logger,
            logging.DEBUG,
            "worker.onchain.disabled",
            "on-chain market creation skipped (missing configuration)",
            event_id=market.event_id,
        )
        return None

    if market.market_address:
        return None

    if not market.oracle:
        log_event(
            logger,
            logging.WARNING,
            "worker.onchain.missing_oracle",
            "cannot create on-chain market without oracle address",
            event_id=market.event_id,
        )
        return None

    commit_deadline = int(time.time()) + settings.default_commit_lead_seconds
    reveal_deadline = commit_deadline + settings.default_reveal_lead_seconds

    try:
        market_address = asyncio.run(
            _send_create_market_transaction(
                rpc_url=rpc_url,
                factory_address=factory_address,
                private_key=account_secret,
                event_id=market.event_id,
                commit_deadline=commit_deadline,
                reveal_deadline=reveal_deadline,
                oracle=market.oracle,
                collateral=market.collateral,
                gas_price_wei=_to_wei(settings.gas_price_gwei),
                max_priority_fee_wei=_to_wei(settings.max_priority_fee_gwei),
                max_retries=settings.max_web3_retries,
            )
        )
    except OnChainConfigurationError as exc:
        log_event(
            logger,
            logging.ERROR,
            "worker.onchain.config_error",
            "on-chain configuration error",
            event_id=market.event_id,
            error=str(exc),
        )
        return None
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.ERROR,
            "worker.tx.failed",
            "createMarket transaction failed",
            event_id=market.event_id,
            error=str(exc),
        )
        return None

    if market_address:
        market.market_address = market_address
        session.flush()
        log_event(
            logger,
            logging.INFO,
            "worker.onchain.market_created",
            "market created on-chain",
            event_id=market.event_id,
            market_address=market_address,
        )
    return market_address


def _to_wei(value_gwei: Optional[float]) -> Optional[int]:
    if value_gwei is None:
        return None
    return int(value_gwei * 1_000_000_000)
