from __future__ import annotations

import logging
from typing import Any, cast

from shared.models import Commitment, Settlement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .merkle import build_merkle_root_and_paths

logger = logging.getLogger("reveal_market.worker.proof_builder")


class SettlementDataMissingError(RuntimeError):
    pass


def build_prover_payload(session: Session, market_id: int) -> dict[str, Any]:
    settlement = session.execute(select(Settlement).where(Settlement.market_id == market_id)).scalar_one_or_none()
    if not settlement:
        raise SettlementDataMissingError("settlement row not found")
    required_fields = [
        settlement.merkle_root,
        settlement.commitments_count,
        settlement.total_escrow,
        settlement.total_liability,
        settlement.rake_bps,
        settlement.winning_outcome_id,
        settlement.circuit_hash,
    ]
    if any(v in (None, 0, "") for v in required_fields):
        raise SettlementDataMissingError("settlement missing required fields")
    if settlement.winning_outcome_id not in (0, 1):
        raise SettlementDataMissingError("winning outcome out of range")

    commitments: list[Commitment] = list(
        session.execute(select(Commitment).where(Commitment.market_id == market_id).order_by(Commitment.id))
        .scalars()
        .all()
    )
    if not commitments:
        raise SettlementDataMissingError("no commitments for market")

    merkle_root = cast(str, settlement.merkle_root)
    total_liability = cast(int, settlement.total_liability)

    leaves = [bytes.fromhex(commitment.leaf.removeprefix("0x")) for commitment in commitments]
    computed_root, _ = build_merkle_root_and_paths(leaves)
    expected_root = bytes.fromhex(merkle_root.removeprefix("0x"))
    if computed_root != expected_root:
        raise SettlementDataMissingError("computed merkle root does not match stored root")

    winning_pool = settlement.pool_total_yes if settlement.winning_outcome_id == 0 else settlement.pool_total_no
    if winning_pool in (None, 0):
        raise SettlementDataMissingError("winning pool missing or zero")

    payload = {
        "marketId": str(market_id),
        "merkleRoot": merkle_root,
        "winningOutcomeId": settlement.winning_outcome_id,
        "poolTotals": [str(settlement.pool_total_yes or 0), str(settlement.pool_total_no or 0)],
        "totalEscrow": str(settlement.total_escrow),
        "totalLiability": str(total_liability),
        "rakeBps": str(settlement.rake_bps or 0),
        "circuitHash": settlement.circuit_hash,
    }
    return payload


async def build_prover_payload_async(session: AsyncSession, market_id: int) -> dict[str, Any]:
    """Async version of build_prover_payload using AsyncSession primitives."""

    settlement = (
        await session.execute(select(Settlement).where(Settlement.market_id == market_id))
    ).scalar_one_or_none()
    if not settlement:
        raise SettlementDataMissingError("settlement row not found")
    required_fields = [
        settlement.merkle_root,
        settlement.commitments_count,
        settlement.total_escrow,
        settlement.total_liability,
        settlement.rake_bps,
        settlement.winning_outcome_id,
        settlement.circuit_hash,
    ]
    if any(v in (None, 0, "") for v in required_fields):
        raise SettlementDataMissingError("settlement missing required fields")
    if settlement.winning_outcome_id not in (0, 1):
        raise SettlementDataMissingError("winning outcome out of range")

    commitments: list[Commitment] = list(
        (await session.execute(select(Commitment).where(Commitment.market_id == market_id).order_by(Commitment.id)))
        .scalars()
        .all()
    )
    if not commitments:
        raise SettlementDataMissingError("no commitments for market")

    merkle_root = cast(str, settlement.merkle_root)
    total_liability = cast(int, settlement.total_liability)

    leaves = [bytes.fromhex(commitment.leaf.removeprefix("0x")) for commitment in commitments]
    computed_root, _ = build_merkle_root_and_paths(leaves)
    expected_root = bytes.fromhex(merkle_root.removeprefix("0x"))
    if computed_root != expected_root:
        raise SettlementDataMissingError("computed merkle root does not match stored root")

    winning_pool = settlement.pool_total_yes if settlement.winning_outcome_id == 0 else settlement.pool_total_no
    if winning_pool in (None, 0):
        raise SettlementDataMissingError("winning pool missing or zero")

    payload = {
        "marketId": str(market_id),
        "merkleRoot": merkle_root,
        "winningOutcomeId": settlement.winning_outcome_id,
        "poolTotals": [str(settlement.pool_total_yes or 0), str(settlement.pool_total_no or 0)],
        "totalEscrow": str(settlement.total_escrow),
        "totalLiability": str(total_liability),
        "rakeBps": str(settlement.rake_bps or 0),
        "circuitHash": settlement.circuit_hash,
    }
    return payload
