"""Settlement automation: build snapshots, request proofs, and submit on-chain transactions."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Awaitable, Sequence
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
from shared.poseidon import BATCH_SIZE
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import AsyncWeb3
from web3.contract.async_contract import AsyncContract
from web3.types import TxParams, Wei

from . import runtime
from .cache_ops import invalidate_cache_tags
from .database import session_scope
from .merkle import build_merkle_root_and_paths
from .metrics import RELAYER_QUEUE_COUNTER

logger = runtime.logger


def _normalize_bytes32(value: Any) -> str | None:
    """Return a 0x-prefixed hex string for bytes/HexBytes values."""

    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    hex_value = getattr(value, "hex", None)
    if callable(hex_value):
        return str(hex_value())
    return str(value)


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _batch_root_for_ticket(settlement: shared_models.Settlement, ticket_id: int) -> str | None:
    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    if batch_roots:
        batch_index = int(ticket_id) // BATCH_SIZE
        if batch_index < len(batch_roots):
            return str(batch_roots[batch_index])
    if _is_empty_hex(getattr(settlement, "merkle_root", None)):
        return None
    return settlement.merkle_root


def _root_to_signal(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value)
    try:
        if raw.lower().startswith("0x"):
            return str(int(raw, 16))
        return str(int(raw))
    except Exception:
        return None


def _raw_tx_bytes(signed_tx: Any) -> bytes:
    # Prefer snake_case (web3/eth-account v7) with camelCase fallback for older versions.
    raw_tx = getattr(signed_tx, "raw_transaction", None)
    if raw_tx is None:
        raw_tx = getattr(signed_tx, "rawTransaction", None)
    if raw_tx is None:  # pragma: no cover - defensive for web3 variants
        raise ValueError("Signed transaction is missing raw transaction bytes")
    return cast(bytes, raw_tx)


def _build_market_contract(web3: AsyncWeb3, market_address: str) -> AsyncContract:
    """Return a typed contract instance for a market address."""

    checksum_address = cast(ChecksumAddress, to_checksum(market_address))
    return web3.eth.contract(address=checksum_address, abi=REVEAL_MARKET_ABI)


def _hex_to_bytes(value: str | None) -> bytes:
    if not value:
        return b""
    cleaned = value.removeprefix("0x")
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return b""


def _is_empty_hex(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (bytes, bytearray)):
        return len(value) == 0 or all(b == 0 for b in value)
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if not cleaned:
        return True
    return all(ch == "0" for ch in cleaned)


def settlement_needs_refresh(settlement: shared_models.Settlement | None) -> bool:
    """Return True when a settlement snapshot is missing critical fields."""

    if settlement is None:
        return True
    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    batch_counts = _parse_json_list(getattr(settlement, "batch_counts", None))
    has_batch_roots = bool(batch_roots)
    has_merkle_root = not _is_empty_hex(getattr(settlement, "merkle_root", None))
    if not has_batch_roots and not has_merkle_root:
        return True
    if _is_empty_hex(settlement.circuit_hash):
        return True
    if settlement.commitments_count and not has_batch_roots and not has_merkle_root:
        return True
    if batch_roots and (not batch_counts or len(batch_counts) != len(batch_roots)):
        return True
    if settlement.commitments_count is None:
        return True
    if settlement.pool_total_yes is None or settlement.pool_total_no is None:
        return True
    if settlement.total_escrow is None or settlement.total_liability is None:
        return True
    if settlement.rake_bps is None:
        return True
    if settlement.winning_outcome_id is None:
        return True
    return False


async def _fetch_onchain_snapshot(web3: AsyncWeb3, market_address: str) -> dict[str, Any]:
    """Return settlement-related state from the on-chain market contract."""

    contract = _build_market_contract(web3, market_address)
    (
        commitments_root,
        next_ticket_id,
        phase_value,
        _commit_deadline,
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
    batch_roots: list[str] = []
    batch_counts: list[int] = []
    try:
        if int(next_ticket_id or 0) > 0:
            total_batches = (int(next_ticket_id) + BATCH_SIZE - 1) // BATCH_SIZE
            for index in range(total_batches):
                root_value = await contract.functions.batchRoots(index).call()
                count_value = await contract.functions.batchCounts(index).call()
                batch_roots.append(_normalize_bytes32(root_value) or str(root_value))
                batch_counts.append(int(count_value))
    except Exception:
        batch_roots = []
        batch_counts = []
    return {
        "commitments_count": int(next_ticket_id),
        "phase": int(phase_value),
        "winning_outcome_id": int(winning_outcome_id) if winning_outcome_id is not None else None,
        "total_escrow": int(total_escrow),
        "total_liability": int(total_liability),
        "pool_total_yes": int(pool_total_yes),
        "pool_total_no": int(pool_total_no),
        "rake_bps": int(rake_bps),
        "commitments_root": _normalize_bytes32(commitments_root),
        "circuit_hash": _normalize_bytes32(circuit_hash),
        "result_posted": result_posted,
        "batch_roots": batch_roots,
        "batch_counts": batch_counts,
    }


async def _upsert_settlement_from_chain(
    session: AsyncSession, market: shared_models.Market, *, force: bool = False
) -> shared_models.Settlement | None:
    """Populate the settlement snapshot from on-chain state when available."""

    if not market.market_address or not runtime.settings.rpc_url:
        return None
    existing = await shared_repository.get_settlement_by_market_id(session, market.id)
    if existing is not None and not force and not settlement_needs_refresh(existing):
        return existing
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
        return existing

    payload = {
        "merkle_root": snapshot.get("commitments_root"),
        "commitments_count": snapshot.get("commitments_count"),
        "batch_roots": snapshot.get("batch_roots"),
        "batch_counts": snapshot.get("batch_counts"),
        "pool_total_yes": snapshot.get("pool_total_yes"),
        "pool_total_no": snapshot.get("pool_total_no"),
        "total_escrow": snapshot.get("total_escrow"),
        "total_liability": snapshot.get("total_liability"),
        "rake_bps": snapshot.get("rake_bps"),
        "winning_outcome_id": snapshot.get("winning_outcome_id"),
        "circuit_hash": snapshot.get("circuit_hash"),
    }
    return await shared_repository.upsert_settlement_snapshot(session, market.id, payload)


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
    tx_hash = await web3.eth.send_raw_transaction(_raw_tx_bytes(signed))
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
    tx_hash = await web3.eth.send_raw_transaction(_raw_tx_bytes(signed))
    receipt = await web3.eth.wait_for_transaction_receipt(tx_hash)
    return tx_hash.hex(), getattr(receipt, "blockNumber", None)


async def _submit_verify_and_settle_batched(
    web3: AsyncWeb3,
    account,
    market_address: str,
    proofs: Sequence[str],
    public_signals: Sequence[Sequence[Any]],
    batch_indexes: Sequence[int],
) -> tuple[str, int | None]:
    contract = _build_market_contract(web3, market_address)
    hydrated_signals = [_hydrate_public_signals(signals) for signals in public_signals]
    proof_bytes = [bytes.fromhex(proof.removeprefix("0x")) for proof in proofs]
    batch_indexes_int = [int(value) for value in batch_indexes]
    base_tx: TxParams = {
        "from": account.address,
        "nonce": await web3.eth.get_transaction_count(account.address),
        "gas": 1_200_000,
    }
    if runtime.settings.settlement_gas_price_gwei is not None:
        base_tx["gasPrice"] = cast(Wei, int(runtime.settings.settlement_gas_price_gwei * 1e9))
    if runtime.settings.settlement_max_priority_fee_gwei is not None:
        base_tx["maxPriorityFeePerGas"] = cast(Wei, int(runtime.settings.settlement_max_priority_fee_gwei * 1e9))
    tx = await contract.functions.verifyAndSettleBatched(proof_bytes, hydrated_signals, batch_indexes_int).build_transaction(
        base_tx
    )
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = await web3.eth.gas_price
    signed = account.sign_transaction(tx)
    tx_hash = await web3.eth.send_raw_transaction(_raw_tx_bytes(signed))
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


async def _build_merkle_proof_for_commitment(
    session: AsyncSession,
    market_db_id: int,
    settlement: shared_models.Settlement,
    commitment: shared_models.Commitment,
) -> list[str]:
    """Return stored merkle path or recompute from existing leaves."""

    path_rows = list(
        (
            await session.execute(
                select(shared_models.CommitmentMerklePath)
                .where(shared_models.CommitmentMerklePath.commitment_id == commitment.id)
                .order_by(shared_models.CommitmentMerklePath.level.asc())
            )
        ).scalars()
    )
    siblings = [row.sibling_hash for row in path_rows] if path_rows else []
    if siblings:
        return siblings

    batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
    batch_counts = _parse_json_list(getattr(settlement, "batch_counts", None))
    if not batch_roots and settlement.merkle_root and not _is_empty_hex(settlement.merkle_root):
        batch_roots = [settlement.merkle_root]
        batch_counts = [settlement.commitments_count]
    if not batch_roots or not batch_counts or len(batch_roots) != len(batch_counts):
        return []
    if commitment.leaf_index is None:
        return []

    batch_index = int(commitment.leaf_index) // BATCH_SIZE
    if batch_index >= len(batch_roots):
        return []
    count_raw = batch_counts[batch_index] if batch_index < len(batch_counts) else None
    try:
        count = int(count_raw or 0)
    except Exception:
        return []
    if count <= 0:
        return []
    index_in_batch = int(commitment.leaf_index) % BATCH_SIZE
    if index_in_batch >= count:
        return []

    commitments = await shared_repository.list_commitments_by_market(session, market_db_id)
    leaves: list[bytes | None] = [None] * count
    for idx, row in enumerate(commitments):
        leaf_bytes = _hex_to_bytes(row.leaf or row.ticket_hash)
        if not leaf_bytes:
            return []
        leaf_index = row.leaf_index if row.leaf_index is not None else idx
        batch_id = int(leaf_index) // BATCH_SIZE
        if batch_id != batch_index:
            continue
        rel_index = int(leaf_index) % BATCH_SIZE
        if rel_index >= count:
            continue
        leaves[rel_index] = leaf_bytes
    if any(leaf is None for leaf in leaves):
        return []
    batch_leaves = cast(list[bytes], leaves)
    try:
        computed_root, paths = build_merkle_root_and_paths(batch_leaves)
        expected_root = bytes.fromhex(str(batch_roots[batch_index]).removeprefix("0x"))
        if computed_root != expected_root:
            return []
        proof = ["0x" + sibling.hex() for sibling in paths[index_in_batch]]
        await shared_repository.replace_merkle_path(session, commitment.id, proof)
        return proof
    except Exception:
        return []


async def _build_relayer_claim_payloads(
    session: AsyncSession, market: shared_models.Market, settlement: shared_models.Settlement
) -> list[dict[str, Any]]:
    """Construct relayer claim payloads for winning commitments."""

    if not market.market_address or settlement.winning_outcome_id is None:
        return []
    winning_outcome = settlement.winning_outcome_id
    payloads: list[dict[str, Any]] = []
    commitments = await shared_repository.list_commitments_by_market(session, market.id)
    for commitment in commitments:
        if commitment.outcome_id != winning_outcome:
            continue
        if commitment.leaf_index is None:
            log_event(
                logger,
                logging.WARNING,
                event="worker.relayer.skip_missing_leaf_index",
                message="skipping relayer claim; commitment missing leaf index",
                market_id=market.event_id,
                commitment_id=getattr(commitment, "id", None),
            )
            continue
        merkle_proof = await _build_merkle_proof_for_commitment(session, market.id, settlement, commitment)
        if not merkle_proof:
            log_event(
                logger,
                logging.WARNING,
                event="worker.relayer.skip_missing_merkle_proof",
                message="skipping relayer claim; merkle proof unavailable",
                market_id=market.event_id,
                commitment_id=getattr(commitment, "id", None),
            )
            continue
        batch_root = _batch_root_for_ticket(settlement, commitment.leaf_index)
        payloads.append(
            {
                "user": commitment.user_address,
                "market": market.market_address,
                "ticket_id": commitment.leaf_index,
                "outcome_id": winning_outcome,
                "amount": int(commitment.amount_wei),
                "salt": commitment.salt or "0x0",
                "merkle_proof": merkle_proof,
                "merkle_root": batch_root,
                "commitments_count": settlement.commitments_count,
                "batch_roots": getattr(settlement, "batch_roots", None),
                "batch_counts": getattr(settlement, "batch_counts", None),
                "pool_total_yes": settlement.pool_total_yes,
                "pool_total_no": settlement.pool_total_no,
                "total_escrow": settlement.total_escrow,
                "total_liability": settlement.total_liability,
                "rake_bps": settlement.rake_bps,
                "proof_request_id": settlement.proof_request_id,
                "event_id": market.event_id,
            }
        )
    return payloads


async def _enqueue_relayer_claims(
    redis_client: Redis | None, market: shared_models.Market, settlement: shared_models.Settlement
) -> int:
    """Queue relayer claim jobs for the given market using the relayer Redis queue."""

    if redis_client is None or not runtime.settings.relayer_queue_enabled or not runtime.settings.relayer_base_url:
        return 0
    try:
        async with session_scope() as session:
            payloads = await _build_relayer_claim_payloads(session, market, settlement)
    except Exception as exc:  # pragma: no cover - defensive
        log_event(
            logger,
            logging.WARNING,
            event="worker.relayer.payload_failed",
            message="failed to build relayer claim payloads",
            error=str(exc),
        )
        RELAYER_QUEUE_COUNTER.labels(outcome="error").inc()
        return 0
    if not payloads:
        return 0
    endpoint = str(runtime.settings.relayer_base_url).rstrip("/") + "/claim"
    enqueued = 0
    now = int(datetime.now(tz=UTC).timestamp())
    for payload in payloads:
        job_id = secrets.token_hex(16)
        body = {
            "job_id": job_id,
            "kind": "claim",
            "endpoint": endpoint,
            "payload": payload,
            "attempts": 0,
            "enqueued_at": now,
        }
        try:
            await cast(Awaitable[Any], redis_client.lpush(runtime.settings.relayer_queue_key, json.dumps(body)))
            enqueued += 1
        except Exception as exc:  # pragma: no cover - redis failures are non-fatal
            log_event(
                logger,
                logging.WARNING,
                event="worker.relayer.enqueue_failed",
                message="failed to enqueue relayer claim job",
                market_id=getattr(market, "event_id", None),
                error=str(exc),
            )
            RELAYER_QUEUE_COUNTER.labels(outcome="error").inc()
            continue
    if enqueued:
        RELAYER_QUEUE_COUNTER.labels(outcome="queued").inc(enqueued)
        log_event(
            logger,
            logging.INFO,
            event="worker.relayer.claims_enqueued",
            message="queued relayer claim jobs",
            count=enqueued,
            market_id=getattr(market, "event_id", None),
        )
    return enqueued


async def run_settlement_jobs(summary, redis_client: Redis | None) -> int:
    """Submit settlement proofs on-chain for markets with generated proofs and no tx hash."""

    relayer_enabled = bool(runtime.settings.relayer_queue_enabled and runtime.settings.relayer_base_url)
    if not runtime.settings.auto_settlement_tx_enabled and not relayer_enabled:
        return 0
    signer_secret = runtime.settings.settlement_signer_private_key
    rpc_url = str(runtime.settings.settlement_rpc_url or runtime.settings.rpc_url or "")
    account = None
    web3: AsyncWeb3 | None = None
    if runtime.settings.auto_settlement_tx_enabled:
        if signer_secret is None or not rpc_url:
            log_event(
                logger,
                logging.DEBUG,
                event="worker.settlement.tx.disabled",
                message="auto-settlement tx disabled (missing signer or rpc)",
            )
            if not relayer_enabled:
                return 0
        else:
            try:
                account = Account.from_key(signer_secret.get_secret_value())
                web3 = get_async_web3(rpc_url)
            except Exception as exc:  # pragma: no cover - config error
                log_event(
                    logger,
                    logging.WARNING,
                    event="worker.settlement.tx.signer_error",
                    message="failed to load settlement signer",
                    error=str(exc),
                )
                if not relayer_enabled:
                    return 0

    submitted = 0
    dirty_events: set[str] = set()
    dirty_conditions: set[str] = set()
    async with session_scope() as session:
        pending = await shared_repository.list_settlements_pending_tx(session)
        for settlement, market in pending:
            event_id = getattr(market, "event_id", None)
            condition_value = getattr(market, "condition_id", None)

            def _mark_dirty(eid: str | None = event_id, cond_val: str | None = condition_value) -> None:
                if eid:
                    dirty_events.add(eid)
                    summary.changed_events.add(eid)
                if isinstance(cond_val, str) and cond_val:
                    normalized = cond_val.lower()
                    dirty_conditions.add(normalized)
                    summary.changed_conditions.add(normalized)

            if not market.market_address:
                continue
            winning_outcome_id = settlement.winning_outcome_id or await _resolve_winning_outcome(session, market)
            if winning_outcome_id is None:
                continue
            batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
            if not batch_roots and _is_empty_hex(settlement.merkle_root):
                # hydrate from chain if possible
                settlement = await _upsert_settlement_from_chain(session, market) or settlement
                batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
            if not runtime.settings.auto_settlement_tx_enabled:
                if relayer_enabled:
                    enqueued = await _enqueue_relayer_claims(redis_client, market, settlement)
                    if enqueued:
                        settlement.submission_status = shared_models.SettlementSubmissionStatus.QUEUED.value
                        settlement.submission_error = None
                        _mark_dirty()
                        session.add(settlement)
                        submitted += enqueued
                continue

            if web3 is None or account is None:
                settlement.submission_status = shared_models.SettlementSubmissionStatus.FAILED.value
                settlement.submission_error = "settlement_tx_unavailable"
                _mark_dirty()
                session.add(settlement)
                continue
            settlement.submission_status = shared_models.SettlementSubmissionStatus.PROCESSING.value
            settlement.submission_error = None
            _mark_dirty()
            session.add(settlement)
            batch_roots = _parse_json_list(getattr(settlement, "batch_roots", None))
            if not batch_roots and settlement.merkle_root and not _is_empty_hex(settlement.merkle_root):
                batch_roots = [settlement.merkle_root]
            if not batch_roots:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.settlement.missing_roots",
                    message="skipping settlement submission due to missing batch roots",
                    market_id=getattr(market, "event_id", None),
                )
                settlement.submission_status = shared_models.SettlementSubmissionStatus.FAILED.value
                settlement.submission_error = "missing_batch_roots"
                _mark_dirty()
                continue

            receipts = list(
                (
                    await session.execute(
                        select(shared_models.SettlementReceipt).where(
                            shared_models.SettlementReceipt.market_id == settlement.market_id
                        )
                    )
                ).scalars()
            )
            receipt_by_root: dict[str, shared_models.SettlementReceipt] = {}
            for receipt in receipts:
                if not receipt.proof or not receipt.public_signals:
                    continue
                signals = receipt.public_signals
                if isinstance(signals, (list, tuple)) and signals:
                    root_signal = str(signals[0])
                    receipt_by_root.setdefault(root_signal, receipt)

            proofs: list[str] = []
            public_signals_list: list[Sequence[Any]] = []
            batch_indexes: list[int] = []
            for index, root in enumerate(batch_roots):
                root_signal = _root_to_signal(root)
                batch_receipt = receipt_by_root.get(root_signal or "")
                if batch_receipt is None or not batch_receipt.proof or not batch_receipt.public_signals:
                    continue
                proofs.append(str(batch_receipt.proof))
                public_signals_list.append(cast(Sequence[Any], batch_receipt.public_signals))
                batch_indexes.append(index)

            if len(proofs) != len(batch_roots):
                log_event(
                    logger,
                    logging.DEBUG,
                    event="worker.settlement.missing_proof",
                    message="skipping settlement submission due to missing batch proofs",
                    market_id=getattr(market, "event_id", None),
                )
                settlement.submission_status = shared_models.SettlementSubmissionStatus.FAILED.value
                settlement.submission_error = "missing_proof_receipt"
                _mark_dirty()
                continue
            try:
                await _maybe_post_result(
                    web3,
                    account,
                    _build_market_contract(web3, market.market_address),
                    winning_outcome_id,
                )
                tx_hash, block_number = await _submit_verify_and_settle_batched(
                    web3,
                    account,
                    market.market_address,
                    proofs,
                    public_signals_list,
                    batch_indexes,
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
                settlement.submission_status = shared_models.SettlementSubmissionStatus.FAILED.value
                settlement.submission_error = str(exc)
                _mark_dirty()
                continue

            settlement.settlement_tx_hash = tx_hash
            settlement.settlement_block_number = block_number
            settlement.settlement_submitted_at = datetime.now(tz=UTC)
            settlement.submission_status = shared_models.SettlementSubmissionStatus.SUBMITTED.value
            _mark_dirty()
            session.add(settlement)
            submitted += 1
            log_event(
                logger,
                logging.INFO,
                event="worker.settlement.tx_submitted",
                message="submitted verifyAndSettleBatched",
                market_id=getattr(market, "event_id", None),
                tx_hash=tx_hash,
                block_number=block_number,
            )
            if relayer_enabled:
                enqueued = await _enqueue_relayer_claims(redis_client, market, settlement)
                submitted += enqueued
        await session.flush()
    if dirty_events or dirty_conditions:
        await invalidate_cache_tags(redis_client, summary)
    return submitted
