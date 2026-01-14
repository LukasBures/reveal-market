from __future__ import annotations

import json
import logging
from typing import Any, cast

from shared.merkle import build_merkle_root_and_paths
from shared.models import Commitment, Market, Settlement
from shared.poseidon import BATCH_SIZE
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

logger = logging.getLogger("reveal_market.worker.proof_builder")


class SettlementDataMissingError(RuntimeError):
    pass


def _normalize_batch_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


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


def _build_batch_payloads(
    settlement: Settlement,
    market_identifier: int | str,
    commitments: list[Commitment],
) -> list[dict[str, Any]]:
    if settlement.winning_outcome_id not in (0, 1):
        raise SettlementDataMissingError("winning outcome out of range")
    batch_roots = _normalize_batch_list(getattr(settlement, "batch_roots", None))
    batch_counts = _normalize_batch_list(getattr(settlement, "batch_counts", None))
    if not batch_roots and settlement.merkle_root and not _is_empty_hex(settlement.merkle_root):
        batch_roots = [settlement.merkle_root]
        batch_counts = [settlement.commitments_count]
    if not batch_roots or not batch_counts or len(batch_roots) != len(batch_counts):
        raise SettlementDataMissingError("batch roots/counts missing")

    # Build batch commitment lookup, preserving explicit leaf indexes.
    by_batch: dict[int, dict[int, Commitment]] = {}
    for commitment in commitments:
        if commitment.leaf_index is None:
            raise SettlementDataMissingError("missing leaf_index")
        batch_index = int(commitment.leaf_index) // BATCH_SIZE
        rel_index = int(commitment.leaf_index) % BATCH_SIZE
        by_batch.setdefault(batch_index, {})[rel_index] = commitment

    payloads: list[dict[str, Any]] = []
    for batch_index, root_value in enumerate(batch_roots):
        count_raw = batch_counts[batch_index] if batch_index < len(batch_counts) else None
        try:
            count = int(count_raw or 0)
        except Exception:
            raise SettlementDataMissingError("invalid batch count") from None
        if count <= 0:
            raise SettlementDataMissingError("invalid batch count")
        batch_commitments = by_batch.get(batch_index, {})
        leaves: list[bytes | None] = [None] * count
        pool_yes = 0
        pool_no = 0
        total_liability = 0
        tickets: list[dict[str, Any]] = []

        for i in range(count):
            batch_commitment = batch_commitments.get(i)
            if batch_commitment is None or batch_commitment.leaf is None or batch_commitment.salt is None:
                raise SettlementDataMissingError("missing commitment data for batch")
            leaf_bytes = bytes.fromhex(batch_commitment.leaf.removeprefix("0x"))
            leaves[i] = leaf_bytes
            amount = int(batch_commitment.amount_wei)
            payout = int(getattr(batch_commitment, "payout_wei", 0) or 0)
            if payout <= 0:
                raise SettlementDataMissingError("missing payout data for batch")
            outcome_id = int(batch_commitment.outcome_id)
            if outcome_id == 0:
                pool_yes += amount
            elif outcome_id == 1:
                pool_no += amount
            if outcome_id == int(settlement.winning_outcome_id):
                total_liability += payout
            tickets.append(
                {
                    "ticketId": str(batch_commitment.leaf_index),
                    "outcomeId": str(outcome_id),
                    "amount": str(amount),
                    "payout": str(payout),
                    "user": str(batch_commitment.user_address or "0x0"),
                    "salt": str(batch_commitment.salt or "0x0"),
                }
            )

        for _ in range(BATCH_SIZE - count):
            tickets.append(
                {
                    "ticketId": "0",
                    "outcomeId": "0",
                    "amount": "0",
                    "payout": "0",
                    "user": "0",
                    "salt": "0",
                }
            )

        if any(leaf is None for leaf in leaves):
            raise SettlementDataMissingError("batch leaves incomplete")
        batch_leaves = cast(list[bytes], leaves)
        computed_root, _ = build_merkle_root_and_paths(batch_leaves)
        expected_root = bytes.fromhex(str(root_value).removeprefix("0x"))
        if computed_root != expected_root:
            raise SettlementDataMissingError("computed batch merkle root does not match stored root")

        total_escrow = pool_yes + pool_no

        payloads.append(
            {
                "marketId": str(market_identifier),
                "merkleRoot": str(root_value),
                "winningOutcomeId": str(settlement.winning_outcome_id),
                "poolTotals": [str(pool_yes), str(pool_no)],
                "totalEscrow": str(total_escrow),
                "totalLiability": str(total_liability),
                "rakeBps": str(settlement.rake_bps or 0),
                "circuitHash": settlement.circuit_hash,
                "batchIndex": str(batch_index),
                "commitmentsCount": str(count),
                "tickets": tickets,
            }
        )
    return payloads


def build_prover_payload(session: Session, market_id: int) -> list[dict[str, Any]]:
    settlement = session.execute(select(Settlement).where(Settlement.market_id == market_id)).scalar_one_or_none()
    if not settlement:
        raise SettlementDataMissingError("settlement row not found")
    required_fields = [settlement.winning_outcome_id, settlement.circuit_hash]
    if any(v in (None, "") for v in required_fields):
        raise SettlementDataMissingError("settlement missing required fields")

    commitments: list[Commitment] = list(
        session.execute(select(Commitment).where(Commitment.market_id == market_id).order_by(Commitment.id))
        .scalars()
        .all()
    )
    if not commitments:
        raise SettlementDataMissingError("no commitments for market")

    market = session.get(Market, market_id)
    market_identifier = market.onchain_market_id if market and market.onchain_market_id is not None else market_id
    return _build_batch_payloads(settlement, market_identifier, commitments)


async def build_prover_payload_async(session: AsyncSession, market_id: int) -> list[dict[str, Any]]:
    """Async version of build_prover_payload using AsyncSession primitives."""

    settlement = (
        await session.execute(select(Settlement).where(Settlement.market_id == market_id))
    ).scalar_one_or_none()
    if not settlement:
        raise SettlementDataMissingError("settlement row not found")
    required_fields = [settlement.winning_outcome_id, settlement.circuit_hash]
    if any(v in (None, "") for v in required_fields):
        raise SettlementDataMissingError("settlement missing required fields")

    commitments: list[Commitment] = list(
        (await session.execute(select(Commitment).where(Commitment.market_id == market_id).order_by(Commitment.id)))
        .scalars()
        .all()
    )
    if not commitments:
        raise SettlementDataMissingError("no commitments for market")

    market = await session.get(Market, market_id)
    market_identifier = market.onchain_market_id if market and market.onchain_market_id is not None else market_id
    return _build_batch_payloads(settlement, market_identifier, commitments)
