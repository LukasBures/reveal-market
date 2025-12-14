"""Settlement automation: build snapshots, request proofs, and submit on-chain transactions."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from eth_account import Account
from eth_typing import ChecksumAddress
from redis.asyncio import Redis
from shared import models as shared_models
from shared import repository_async as shared_repository
from shared.logging import log_event
from shared.onchain import get_async_web3, to_checksum
from shared.onchain.abi import REVEAL_MARKET_ABI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import AsyncWeb3
from web3.contract.async_contract import AsyncContract
from web3.types import TxParams, Wei

from . import runtime
from .cache_ops import invalidate_cache_tags
from .database import session_scope

logger = runtime.logger


def _build_market_contract(web3: AsyncWeb3, market_address: str) -> AsyncContract:
    """Return a typed contract instance for a market address."""

    checksum_address = cast(ChecksumAddress, to_checksum(market_address))
    return web3.eth.contract(address=checksum_address, abi=REVEAL_MARKET_ABI)


async def _fetch_onchain_snapshot(web3: AsyncWeb3, market_address: str) -> dict[str, Any]:
    """Return settlement-related state from the on-chain market contract."""

    contract = _build_market_contract(web3, market_address)
    (
        commitments_root,
        next_ticket_id,
        phase_value,
        _commit_deadline,
        _reveal_deadline,
        winning_outcome_id,
    ) = await contract.functions.marketState().call()
    total_escrow = await contract.functions.totalEscrow().call()
    total_liability = await contract.functions.totalLiability().call()
    pool_total_yes = await contract.functions.poolTotalYes().call()
    pool_total_no = await contract.functions.poolTotalNo().call()
    rake_bps = await contract.functions.rakeBps().call()
    circuit_hash = await contract.functions.circuitHash().call()
    try:
        result_posted = bool(await contract.functions.resultPosted().call())
    except Exception:
        result_posted = winning_outcome_id is not None
    return {
        "commitments_root": commitments_root,
        "commitments_count": int(next_ticket_id),
        "phase": int(phase_value),
        "winning_outcome_id": int(winning_outcome_id) if winning_outcome_id is not None else None,
        "total_escrow": int(total_escrow),
        "total_liability": int(total_liability),
        "pool_total_yes": int(pool_total_yes),
        "pool_total_no": int(pool_total_no),
        "rake_bps": int(rake_bps),
        "circuit_hash": circuit_hash,
        "result_posted": result_posted,
    }


async def _upsert_settlement_from_chain(
    session: AsyncSession, market: shared_models.Market
) -> shared_models.Settlement | None:
    """Populate the settlement snapshot from on-chain state when available."""

    if not market.market_address or not runtime.settings.rpc_url:
        return None
    web3 = get_async_web3(str(runtime.settings.rpc_url))
    try:
        snapshot = await _fetch_onchain_snapshot(web3, market.market_address)
    except Exception as exc:  # pragma: no cover - network/execution errors
        log_event(
            logger,
            logging.WARNING,
            event="worker.settlement.chain_fetch_failed",
            message="failed to load settlement snapshot from chain",
            market_id=getattr(market, "event_id", None),
            error=str(exc),
        )
        return None

    payload = {
        "merkle_root": snapshot.get("commitments_root"),
        "commitments_count": snapshot.get("commitments_count"),
        "pool_total_yes": snapshot.get("pool_total_yes"),
        "pool_total_no": snapshot.get("pool_total_no"),
        "total_escrow": snapshot.get("total_escrow"),
        "total_liability": snapshot.get("total_liability"),
        "rake_bps": snapshot.get("rake_bps"),
        "winning_outcome_id": snapshot.get("winning_outcome_id"),
        "circuit_hash": snapshot.get("circuit_hash"),
    }
    await shared_repository.upsert_settlement_snapshot(session, market.id, payload)
    return (
        await session.execute(select(shared_models.Settlement).where(shared_models.Settlement.market_id == market.id))
    ).scalar_one_or_none()


def _hydrate_public_signals(public_signals: Sequence[Any]) -> list[int]:
    signals: list[int] = []
    for value in list(public_signals)[:10]:
        try:
            signals.append(int(value))
        except Exception as exc:
            raise ValueError("publicSignals must be numeric") from exc
    if len(signals) != 10:
        raise ValueError("publicSignals length must be 10")
    return signals


async def _maybe_post_result(web3: AsyncWeb3, account, contract, winning_outcome_id: int) -> None:
    try:
        posted = await contract.functions.resultPosted().call()
        if posted:
            return
    except Exception as exc:
        # Best-effort; proceed to submit if missing
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.result_check_failed",
            message="failed to check resultPosted",
            error=str(exc),
        )
    tx_params: TxParams = {
        "from": account.address,
        "nonce": await web3.eth.get_transaction_count(account.address),
    }
    tx = await contract.functions.postResult(int(winning_outcome_id)).build_transaction(tx_params)
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = await web3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = await web3.eth.send_raw_transaction(signed.rawTransaction)
    receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    log_event(
        logger,
        logging.INFO,
        event="worker.settlement.post_result",
        message="posted winning outcome on-chain",
        tx_hash=tx_hash.hex(),
        block_number=getattr(receipt, "blockNumber", None),
    )


async def _submit_verify_and_settle(
    web3: AsyncWeb3,
    account,
    market_address: str,
    proof: str,
    public_signals: Sequence[Any],
) -> tuple[str, int | None]:
    contract = _build_market_contract(web3, market_address)
    signals = _hydrate_public_signals(public_signals)
    proof_bytes = bytes.fromhex(proof.removeprefix("0x"))
    base_tx: TxParams = {
        "from": account.address,
        "nonce": await web3.eth.get_transaction_count(account.address),
        "gas": 800_000,
    }
    # Apply optional gas overrides
    if runtime.settings.settlement_gas_price_gwei is not None:
        base_tx["gasPrice"] = cast(Wei, int(runtime.settings.settlement_gas_price_gwei * 1e9))
    if runtime.settings.settlement_max_priority_fee_gwei is not None:
        base_tx["maxPriorityFeePerGas"] = cast(Wei, int(runtime.settings.settlement_max_priority_fee_gwei * 1e9))
    tx = await contract.functions.verifyAndSettle(proof_bytes, signals).build_transaction(base_tx)
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = await web3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = await web3.eth.send_raw_transaction(signed.rawTransaction)
    receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    return tx_hash.hex(), getattr(receipt, "blockNumber", None)


async def _resolve_winning_outcome(session: AsyncSession, market: shared_models.Market) -> int | None:
    resolution = None
    if market.condition_id:
        resolution = await shared_repository.get_resolution_by_condition_id(session, market.condition_id)
    if resolution and resolution.winning_outcome_id is not None:
        try:
            return int(resolution.winning_outcome_id)
        except Exception:
            return None
    return None


async def run_settlement_jobs(summary, redis_client: Redis | None) -> int:
    """Submit settlement proofs on-chain for markets with generated proofs and no tx hash."""

    if not runtime.settings.auto_settlement_tx_enabled:
        return 0
    signer_secret = runtime.settings.settlement_signer_private_key
    rpc_url = str(runtime.settings.settlement_rpc_url or runtime.settings.rpc_url or "")
    if signer_secret is None or not rpc_url:
        log_event(
            logger,
            logging.DEBUG,
            event="worker.settlement.tx.disabled",
            message="auto-settlement tx disabled (missing signer or rpc)",
        )
        return 0
    try:
        account = Account.from_key(signer_secret.get_secret_value())
    except Exception as exc:  # pragma: no cover - config error
        log_event(
            logger,
            logging.WARNING,
            event="worker.settlement.tx.signer_error",
            message="failed to load settlement signer",
            error=str(exc),
        )
        return 0

    web3 = get_async_web3(rpc_url)
    submitted = 0
    async with session_scope() as session:
        pending = await shared_repository.list_settlements_pending_tx(session)
        for settlement, market in pending:
            if not market.market_address:
                continue
            winning_outcome_id = settlement.winning_outcome_id or await _resolve_winning_outcome(session, market)
            if winning_outcome_id is None:
                continue
            if settlement.merkle_root is None:
                # hydrate from chain if possible
                settlement = await _upsert_settlement_from_chain(session, market) or settlement
            receipt = None
            if settlement.proof_request_id:
                receipt = await shared_repository.get_settlement_receipt_by_request_id(
                    session, settlement.proof_request_id
                )
            if receipt is None or not receipt.proof or not receipt.public_signals:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.settlement.missing_proof",
                    message="skipping settlement submission due to missing proof receipt",
                    market_id=getattr(market, "event_id", None),
                )
                continue
            proof = receipt.proof
            try:
                public_signals: Sequence[Any] = cast(Sequence[Any], receipt.public_signals or [])
                await _maybe_post_result(
                    web3,
                    account,
                    _build_market_contract(web3, market.market_address),
                    winning_outcome_id,
                )
                tx_hash, block_number = await _submit_verify_and_settle(
                    web3,
                    account,
                    market.market_address,
                    proof,
                    public_signals,
                )
            except Exception as exc:  # pragma: no cover - on-chain errors
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.settlement.tx_failed",
                    message="failed to submit settlement tx",
                    market_id=getattr(market, "event_id", None),
                    error=str(exc),
                )
                continue

            settlement.settlement_tx_hash = tx_hash
            settlement.settlement_block_number = block_number
            settlement.settlement_submitted_at = datetime.now(tz=UTC)
            session.add(settlement)
            summary.changed_events.add(getattr(market, "event_id", ""))
            submitted += 1
            log_event(
                logger,
                logging.INFO,
                event="worker.settlement.tx_submitted",
                message="submitted verifyAndSettle",
                market_id=getattr(market, "event_id", None),
                tx_hash=tx_hash,
                block_number=block_number,
            )
        await session.flush()
    if submitted:
        await invalidate_cache_tags(redis_client, summary)
    return submitted
