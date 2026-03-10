#!/usr/bin/env python3
"""Generate settlement proofs for markets stuck with proof_status='none'.

Connects to the database, builds prover payloads, calls the prover service,
and persists the proofs.  Markets are processed one at a time to stay within
the prover's capacity (each proof takes ~30-50s).

Usage (inside the worker container or on a host with access to the DB and prover):
    python scripts/generate_stuck_proofs.py [--market-ids 350 1027 1302 2907]

Environment variables:
    RM_DATABASE_ASYNC_URL  – asyncpg database URL
    RM_PROVER_BASE_URL     – prover HTTP endpoint (e.g. http://prover:8085)
    RM_PROVER_SHARED_SECRET – prover shared secret
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Bootstrap: ensure worker & shared packages are importable
# ---------------------------------------------------------------------------
# Works both from the repo root (local dev) and inside the worker container
# where the layout is /worker/{app,shared,run.py}.
backend_root = os.path.join(os.path.dirname(__file__), os.pardir, "backend")
for sub in ("shared", "worker"):
    path = os.path.join(backend_root, sub)
    if path not in sys.path:
        sys.path.insert(0, os.path.abspath(path))
# Inside the Docker worker container the cwd is /worker
container_root = "/worker"
if os.path.isdir(container_root) and container_root not in sys.path:
    sys.path.insert(0, container_root)

from shared import models as shared_models  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("generate_stuck_proofs")


async def build_prover_payload(session: AsyncSession, market_id: int) -> list[dict]:
    """Build prover payloads from DB data (mirrors proof_builder.py)."""
    try:
        from app.proof_builder import build_prover_payload_async  # inside worker container
    except ImportError:
        from worker.app.proof_builder import build_prover_payload_async  # local dev

    return await build_prover_payload_async(session, market_id)


async def call_prover(base_url: str, secret: str, payload: dict) -> dict:
    """POST to the prover and return the proof response."""
    headers = {
        "Content-Type": "application/json",
        "X-Prover-Secret": secret,
        "X-Request-Id": payload.get("request_id", f"manual-{int(time.time())}"),
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{base_url}/api/v1/proofs/settlement", json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def persist_proof(
    session: AsyncSession,
    market_id: int,
    market_address: str | None,
    batch_index: int,
    response: dict,
    payload: dict,
) -> None:
    """Write the proof to the settlement and settlement_receipt tables."""
    proof_bytes_hex = response.get("proof", "")
    public_signals = response.get("public_signals", [])
    circuit_hash = response.get("circuit_hash")
    prover_version = response.get("prover_version")
    request_id = response.get("request_id", payload.get("request_id", ""))
    generated_at_str = response.get("generated_at")
    generated_at = datetime.fromisoformat(generated_at_str) if generated_at_str else datetime.now(UTC)

    # Compute proof hash (matches worker proofs.py: keccak of proof JSON + joined signals)
    try:
        from eth_utils import keccak

        proof_hash_source = (proof_bytes_hex or "") + "".join(str(s) for s in public_signals)
        proof_hash = "0x" + keccak(proof_hash_source.encode()).hex()
    except ImportError:
        signals_joined = "".join(str(s) for s in public_signals)
        proof_hash = "0x" + hashlib.sha3_256((proof_bytes_hex or "").encode() + signals_joined.encode()).hexdigest()

    # Upsert SettlementReceipt
    existing_receipt = (
        await session.execute(
            select(shared_models.SettlementReceipt).where(
                shared_models.SettlementReceipt.market_id == market_id,
                shared_models.SettlementReceipt.request_id == request_id,
            )
        )
    ).scalar_one_or_none()
    if existing_receipt:
        existing_receipt.proof = proof_bytes_hex
        existing_receipt.proof_hash = proof_hash
        existing_receipt.public_signals = public_signals
        existing_receipt.circuit_hash = circuit_hash
        existing_receipt.prover_version = prover_version
        existing_receipt.generated_at = generated_at
        existing_receipt.batch_index = batch_index
    else:
        receipt = shared_models.SettlementReceipt(
            market_id=market_id,
            market_address=market_address,
            request_id=request_id,
            proof=proof_bytes_hex,
            proof_hash=proof_hash,
            public_signals=public_signals,
            circuit_hash=circuit_hash,
            prover_version=prover_version,
            generated_at=generated_at,
            batch_index=batch_index,
        )
        session.add(receipt)

    # Update Settlement status
    settlement = (
        await session.execute(select(shared_models.Settlement).where(shared_models.Settlement.market_id == market_id))
    ).scalar_one_or_none()
    if settlement:
        settlement.proof_status = shared_models.SettlementProofStatus.GENERATED.value
        settlement.proof_request_id = request_id
        settlement.proof_hash = proof_hash
        session.add(settlement)

    await session.flush()


async def generate_proof_for_market(
    engine,
    prover_url: str,
    prover_secret: str,
    market_id: int,
) -> bool:
    """Generate and persist a proof for a single market. Returns True on success."""
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        market = await session.get(shared_models.Market, market_id)
        if not market:
            logger.error("Market %d not found", market_id)
            return False

        settlement = (
            await session.execute(
                select(shared_models.Settlement).where(shared_models.Settlement.market_id == market_id)
            )
        ).scalar_one_or_none()
        if not settlement:
            logger.error("Settlement not found for market %d", market_id)
            return False
        if settlement.proof_status == shared_models.SettlementProofStatus.GENERATED.value:
            logger.info("Market %d already has proof generated, skipping", market_id)
            return True
        if settlement.winning_outcome_id is None:
            logger.error("Market %d has no winning_outcome_id set", market_id)
            return False

        logger.info(
            "Building prover payload for market %d (address=%s, winner=%s)",
            market_id,
            market.market_address,
            settlement.winning_outcome_id,
        )
        try:
            payloads = await build_prover_payload(session, market_id)
        except Exception as exc:
            logger.error("Failed to build payload for market %d: %s", market_id, exc)
            return False

    # Call prover for each batch (most markets have 1 batch)
    for i, payload in enumerate(payloads):
        batch_label = f"batch {i}/{len(payloads)}"
        logger.info("Calling prover for market %d %s ...", market_id, batch_label)
        start = time.monotonic()
        try:
            response = call_prover(prover_url, prover_secret, payload)
            if asyncio.iscoroutine(response):
                response = await response
        except Exception as exc:
            logger.error("Prover call failed for market %d %s: %s", market_id, batch_label, exc)
            return False
        elapsed = time.monotonic() - start
        logger.info("Proof generated for market %d %s in %.1fs", market_id, batch_label, elapsed)

        # Persist
        async with async_session() as session:
            try:
                await persist_proof(
                    session,
                    market_id,
                    market.market_address,
                    batch_index=i,
                    response=response,
                    payload=payload,
                )
                await session.commit()
                logger.info("Proof persisted for market %d %s", market_id, batch_label)
            except Exception as exc:
                logger.error("Failed to persist proof for market %d: %s", market_id, exc)
                await session.rollback()
                return False

    return True


async def main():
    parser = argparse.ArgumentParser(description="Generate settlement proofs for stuck markets")
    parser.add_argument(
        "--market-ids",
        nargs="+",
        type=int,
        help="Market IDs to generate proofs for (default: auto-detect stuck markets)",
    )
    parser.add_argument("--db-url", default=os.environ.get("RM_DATABASE_ASYNC_URL"))
    parser.add_argument("--prover-url", default=os.environ.get("RM_PROVER_BASE_URL"))
    parser.add_argument("--prover-secret", default=os.environ.get("RM_PROVER_SHARED_SECRET"))
    args = parser.parse_args()

    if not args.db_url:
        logger.error("RM_DATABASE_ASYNC_URL not set")
        sys.exit(1)
    if not args.prover_url:
        logger.error("RM_PROVER_BASE_URL not set")
        sys.exit(1)

    engine = create_async_engine(args.db_url, echo=False)

    market_ids = args.market_ids
    if not market_ids:
        # Auto-detect stuck markets
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            stmt = (
                select(shared_models.Market.id)
                .join(shared_models.Settlement, shared_models.Settlement.market_id == shared_models.Market.id)
                .join(
                    shared_models.Commitment,
                    shared_models.Commitment.market_id == shared_models.Market.id,
                )
                .where(shared_models.Market.resolution_status == shared_models.ResolutionStatusEnum.FINAL.value)
                .where(shared_models.Settlement.proof_status != shared_models.SettlementProofStatus.GENERATED.value)
                .where(shared_models.Settlement.winning_outcome_id.isnot(None))
                .distinct()
                .order_by(shared_models.Market.id.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            market_ids = list(rows)

    if not market_ids:
        logger.info("No stuck markets found")
        await engine.dispose()
        return

    logger.info("Will generate proofs for %d markets: %s", len(market_ids), market_ids)

    success = 0
    failed = 0
    for mid in market_ids:
        ok = await generate_proof_for_market(engine, args.prover_url, args.prover_secret or "", mid)
        if ok:
            success += 1
        else:
            failed += 1
        # Brief pause between markets to avoid overloading the prover
        if mid != market_ids[-1]:
            logger.info("Waiting 5s before next market...")
            await asyncio.sleep(5)

    logger.info("Done. success=%d failed=%d", success, failed)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
