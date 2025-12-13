"""Trade orchestration routes tying quotes to relayer commits."""

from __future__ import annotations

import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException, status
from shared.logging import log_event
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3

from app import repository_async, schemas
from app.routes import pricing as pricing_routes
from app.database import get_session
from app.runtime import logger, settings

router = APIRouter()


def _strip_hex(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


async def _get_quote(session: AsyncSession, quote_id: str) -> tuple[Any, schemas.PricingQuotePayload]:
    db_quote = await repository_async.get_quote(session, quote_id)
    if db_quote is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quote_not_found")
    if db_quote.status != "issued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="quote_already_consumed")
    payload = db_quote.payload
    try:
        return db_quote, schemas.PricingQuotePayload.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid_quote_payload: {exc}") from exc


def _require_auth_signer():
    raw = settings.authorization_signer_private_key
    if raw is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth_signer_missing")
    return raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)


async def _ensure_market(
    session: AsyncSession, market_id: str, expected_address: str | None
) -> tuple[int, str, int | None]:
    market = await repository_async.get_market_by_event_id(session, market_id)
    if market is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="market_not_found")
    if not expected_address:
        if market.market_address:
            return market.id, market.market_address, market.onchain_market_id
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="market_address_missing")
    if market.market_address and market.market_address.lower() != expected_address.lower():
        log_event(
            logger,
            logging.WARNING,
            event="trade.market_address_mismatch",
            message="Market address mismatch between quote and DB",
            market_id=market_id,
            quote_address=expected_address,
            db_address=market.market_address,
        )
    return market.id, expected_address, market.onchain_market_id


@router.post("/trade/commit", response_model=schemas.TradeCommitResponse, tags=["trade"])
async def trade_commit(
    payload: schemas.TradeCommitRequest,
    session: AsyncSession = Depends(get_session),
) -> schemas.TradeCommitResponse:
    """Consume a pricing quote, build CommitAuth, and forward to the relayer."""

    db_quote, quote = await _get_quote(session, payload.quote_id)
    now = datetime.now(tz=UTC)
    if quote.expires_at and quote.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quote_expired")

    market_db_id, market_address, market_onchain_id = await _ensure_market(
        session, quote.market_id or "", quote.market_address
    )
    chain_id = settings.pricing_chain_id
    if chain_id is None or quote.chain_id != chain_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quote_chain_mismatch")

    ticket_size_wei = int(settings.ticket_size_wei)
    if int(quote.stake_wei) != ticket_size_wei:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"stake_mismatch_expected_{ticket_size_wei}",
        )

    # Validate and consume the quote using the existing submit logic (signature + drift checks).
    await pricing_routes.pricing_submit(
        schemas.PricingSubmitRequest(quote=quote, max_fx_diff_percent=payload.max_fx_diff_percent),
        session=session,
    )

    # Count existing commitments to derive next ticket id (MVP assumption: all commits go through this path).
    ticket_id = await repository_async.count_commitments(session, market_db_id)
    salt_bytes = secrets.token_bytes(32)
    salt_hex = "0x" + salt_bytes.hex()
    commitment = Web3.solidity_keccak(
        ["uint256", "uint256", "uint256", "bytes32"],
        [ticket_id, int(quote.outcome_id), ticket_size_wei, salt_bytes],
    ).hex()

    nonce = secrets.randbelow(2**256 - 1)
    expiry = int(time.time()) + int(settings.commit_nonce_ttl_seconds)
    auth_digest = Web3.solidity_keccak(
        ["address", "uint256", "bytes32", "uint256", "uint256"],
        [Web3.to_checksum_address(market_address), int(market_onchain_id or 0), bytes.fromhex(_strip_hex(commitment)), nonce, expiry],
    )
    auth_signer_key = _require_auth_signer()
    signed = Account.sign_message(encode_defunct(hexstr=auth_digest.hex()), auth_signer_key)

    if not settings.relayer_base_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="relayer_unconfigured")
    relayer_payload = {
        "user": quote.wallet_address,
        "market": market_address,
        "commitment": commitment,
        "nonce": nonce,
        "expiry": expiry,
        "signature": signed.signature.hex(),
        "ticket_value_wei": ticket_size_wei,
    }
    headers = {}
    if settings.relayer_bearer_token:
        headers["Authorization"] = f"Bearer {settings.relayer_bearer_token}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{settings.relayer_base_url}/commit", json=relayer_payload, headers=headers)
        if resp.status_code not in (200, 202):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"relayer_error:{resp.status_code}:{resp.text}",
            )
        relayer_result = resp.json()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - network errors
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    tx_hash = relayer_result.get("txHash") or relayer_result.get("tx_hash") or relayer_result.get("jobId")

    # Persist commitment snapshot.
    await repository_async.record_commitments(
        session,
        market_db_id,
        [
            {
                "ticketHash": commitment,
                "leaf": commitment,
                "user": quote.wallet_address,
                "outcomeId": quote.outcome_id,
                "amount": ticket_size_wei,
                "salt": salt_hex,
                "merkleIndex": ticket_id,
            }
        ],
    )
    await session.flush()

    stake_zen = float(quote.stake_zen)
    entry_fx = float(quote.zen_usd)
    potential = None
    try:
        profit_usd = float(quote.hedge_usdc) * float(quote.displayed_odds_multiplier) - float(quote.hedge_usdc)
        potential = (profit_usd / entry_fx) + stake_zen if entry_fx > 0 else None
    except Exception:
        potential = None

    return schemas.TradeCommitResponse(
        tx_hash=str(tx_hash) if tx_hash else "",
        quote_id=payload.quote_id,
        market_id=quote.market_id or "",
        outcome_id=int(quote.outcome_id),
        stake_zen=stake_zen,
        entry_fx=entry_fx,
        potential_payout_zen=potential,
        status="committed",
        ticket_id=ticket_id,
        salt=salt_hex,
    )


@router.get("/positions", response_model=list[schemas.PositionRecord], tags=["trade"])
async def list_positions(wallet: str, session: AsyncSession = Depends(get_session)) -> list[schemas.PositionRecord]:
    """Return committed positions for a wallet (best-effort until settlements are wired)."""

    if not wallet:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wallet_required")
    rows = await repository_async.list_commitments_for_wallet(session, wallet)
    positions: list[schemas.PositionRecord] = []
    for commitment, market in rows:
        stake_wei = int(commitment.amount_wei)
        stake_zen = stake_wei / 1e18
        positions.append(
            schemas.PositionRecord(
                market_id=market.event_id,
                market_title=market.title,
                outcome_id=commitment.outcome_id,
                stake_wei=stake_wei,
                stake_zen=stake_zen,
                tx_hash=None,
                quote_id=None,
                status="committed",
                ticket_id=commitment.leaf_index,
                created_at=getattr(commitment, "created_at", None),
            )
        )
    return positions
