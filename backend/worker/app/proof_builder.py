from __future__ import annotations

import logging
from typing import Any

from eth_utils import to_checksum_address
from shared.models import Commitment, Settlement
from sqlalchemy import select
from sqlalchemy.orm import Session

from .merkle import build_merkle_root_and_paths

logger = logging.getLogger("reveal_market.worker.proof_builder")


class SettlementDataMissing(RuntimeError):
    pass


def _hex_bytes(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, str):
        return value if value.startswith("0x") else "0x" + value
    raise TypeError("unsupported type for hex conversion")


def build_prover_payload(session: Session, market_id: int) -> dict[str, Any]:
    settlement = session.execute(select(Settlement).where(Settlement.market_id == market_id)).scalar_one_or_none()
    if not settlement:
        raise SettlementDataMissing("settlement row not found")
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
        raise SettlementDataMissing("settlement missing required fields")

    commitments: list[Commitment] = (
        session.execute(select(Commitment).where(Commitment.market_id == market_id).order_by(Commitment.id))
        .scalars()
        .all()
    )
    if not commitments:
        raise SettlementDataMissing("no commitments for market")

    leaves = [bytes.fromhex(commitment.leaf.removeprefix("0x")) for commitment in commitments]
    computed_root, paths = build_merkle_root_and_paths(leaves)
    expected_root = bytes.fromhex(settlement.merkle_root.removeprefix("0x"))
    if computed_root != expected_root:
        raise SettlementDataMissing("computed merkle root does not match stored root")

    tickets: list[dict[str, Any]] = []
    for idx, commitment in enumerate(commitments):
        if settlement.commitments_count and idx >= settlement.commitments_count:
            break
        merkle_path = paths[idx] if idx < len(paths) else []
        tickets.append(
            {
                "user": to_checksum_address(commitment.user_address),
                "outcomeId": str(commitment.outcome_id),
                "amount": str(commitment.amount_wei),
                "salt": commitment.salt or "0x0",
                "ticketHash": _hex_bytes(commitment.ticket_hash),
                "leaf": _hex_bytes(commitment.leaf),
                "merklePath": [_hex_bytes(x) for x in merkle_path],
                "merkleIndex": idx,
            }
        )

    payload = {
        "marketId": str(market_id),
        "merkleRoot": settlement.merkle_root,
        "winningOutcomeId": settlement.winning_outcome_id,
        "poolTotals": [str(settlement.pool_total_yes or 0), str(settlement.pool_total_no or 0)],
        "totalEscrow": str(settlement.total_escrow),
        "totalLiability": str(settlement.total_liability),
        "rakeBps": str(settlement.rake_bps or 0),
        "circuitHash": settlement.circuit_hash,
        "tickets": tickets,
    }
    return payload
