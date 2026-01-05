"""Pricing and signed quote routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from secrets import token_hex
from typing import cast

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import SecretStr
from shared import models as shared_models
from shared.logging import log_event
from shared.onchain.client import load_account
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3

from app import models, repository_async, schemas
from app.database import get_session
from app.metrics_registry import PRICING_COUNTER
from app.pricing import PricingEngine, fetch_fx_quote
from app.runtime import logger, settings

router = APIRouter()


def _strip_0x(value: str | None) -> str:
    """Remove 0x prefix from hex strings."""

    if not value:
        return ""
    return value[2:] if value.startswith("0x") else value


def _to_wei_amount(stake_zen: float | Decimal) -> int:
    """Scale a ZEN stake to wei with safe rounding."""

    quantized = (Decimal(str(stake_zen)) * Decimal("1e18")).to_integral_value(rounding=ROUND_DOWN)
    return int(quantized)


def _scale_fx_value(zen_usd: float | Decimal) -> int:
    """Scale FX price to 1e8 for the on-chain digest."""

    quantized = (Decimal(str(zen_usd)) * Decimal("1e8")).to_integral_value(rounding=ROUND_DOWN)
    return int(quantized)


def _assert_commits_allowed(
    market: shared_models.Market,
    now: datetime,
    session: AsyncSession | None = None,
) -> None:
    """Raise if the market should not accept new quotes/commits."""

    # Enforce a minimum 5-minute buffer before close; use configured cutoff if larger.
    cutoff_seconds = max(300, getattr(settings, "commit_cutoff_seconds", 0) or 0)
    resolution_status = getattr(market, "resolution_status", shared_models.ResolutionStatusEnum.FINAL.value)
    resolution_reason = getattr(market, "resolution_reason", None)
    blocked_at = getattr(market, "commits_blocked_at", None)

    def _normalize_ts(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    if resolution_status in {
        shared_models.ResolutionStatusEnum.PENDING.value,
        shared_models.ResolutionStatusEnum.DISPUTED.value,
    }:
        if blocked_at is None:
            market.commits_blocked_at = now
            blocked_at = market.commits_blocked_at
        blocked_at_ts = _normalize_ts(blocked_at)
        if session is not None:
            session.add(market)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "market_resolution_pending",
                "resolution_status": resolution_status,
                "resolution_reason": resolution_reason,
                "commits_blocked_at": blocked_at_ts.isoformat() if blocked_at_ts else None,
            },
        )
    closes_at = _normalize_ts(getattr(market, "closes_at", None))
    if cutoff_seconds > 0 and closes_at is not None:
        cutoff_time = closes_at - timedelta(seconds=int(cutoff_seconds))
        if now >= cutoff_time:
            block_time = cutoff_time
            blocked_at_ts = _normalize_ts(blocked_at)
            if blocked_at_ts is None or blocked_at_ts > block_time:
                market.commits_blocked_at = block_time
                blocked_at = market.commits_blocked_at
                blocked_at_ts = block_time
            if session is not None:
                session.add(market)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "market_near_resolution",
                    "closes_at": closes_at.isoformat(),
                    "cutoff_seconds": cutoff_seconds,
                    "commits_blocked_at": blocked_at_ts.isoformat() if blocked_at_ts else None,
                },
            )
    if getattr(market, "closed", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Market is closed; new quotes are disabled",
        )


def build_quote_digest(
    chain_id: int,
    market_address: str,
    wallet_address: str,
    outcome_id: int,
    stake_wei: int,
    zen_usd_scaled: int,
    expiry_ts: int,
    quote_id_hex: str,
) -> bytes:
    """Build the QUOTE_V1 digest matching the on-chain verifier."""

    quote_bytes = bytes.fromhex(_strip_0x(quote_id_hex))
    if len(quote_bytes) != 32:
        raise ValueError("quote_id must be 32 bytes hex")
    return Web3.solidity_keccak(
        [
            "string",
            "uint256",
            "address",
            "address",
            "uint256",
            "uint256",
            "uint256",
            "uint256",
            "bytes32",
        ],
        [
            "QUOTE_V1",
            int(chain_id),
            Web3.to_checksum_address(market_address),
            Web3.to_checksum_address(wallet_address),
            int(outcome_id),
            int(stake_wei),
            int(zen_usd_scaled),
            int(expiry_ts),
            quote_bytes,
        ],
    )


async def _enforce_caps(
    session: AsyncSession,
    *,
    stake_zen: Decimal,
    market_id: str | None,
    wallet_address: str | None,
    include_stake: bool = True,
    exclude_quote: models.Quote | None = None,
    statuses: set[str] | None = None,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Validate stake caps and return projected totals and remaining allowances."""

    await repository_async.expire_stale_quotes(session)
    window = settings.bet_cap_ttl_seconds
    status_filter = statuses
    market_total = None
    user_total = None
    if market_id:
        market_existing = float(
            await repository_async.sum_quote_stakes(
                session, market_id=market_id, window_seconds=window, statuses=status_filter
            )
        )
        if exclude_quote and exclude_quote.market_id == market_id:
            market_existing = max(0.0, market_existing - float(exclude_quote.stake_zen))
        projected_market = market_existing + (float(stake_zen) if include_stake else 0.0)
        if projected_market > settings.max_market_stake_zen:
            remaining = max(0.0, settings.max_market_stake_zen - market_existing)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "market_cap_exceeded",
                    "max_market_stake_zen": settings.max_market_stake_zen,
                    "remaining_market_stake_zen": remaining,
                    "stake_zen": float(stake_zen),
                    "market_id": market_id,
                },
            )
        market_total = projected_market

    if market_id and wallet_address:
        user_existing = float(
            await repository_async.sum_quote_stakes(
                session,
                market_id=market_id,
                wallet_address=wallet_address,
                window_seconds=window,
                statuses=status_filter,
            )
        )
        if exclude_quote and exclude_quote.market_id == market_id and exclude_quote.wallet_address == wallet_address:
            user_existing = max(0.0, user_existing - float(exclude_quote.stake_zen))
        projected_user = user_existing + (float(stake_zen) if include_stake else 0.0)
        if projected_user > settings.max_user_stake_per_market_zen:
            remaining_user_cap = max(0.0, settings.max_user_stake_per_market_zen - user_existing)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "user_market_cap_exceeded",
                    "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen,
                    "remaining_user_stake_zen": remaining_user_cap,
                    "stake_zen": float(stake_zen),
                    "market_id": market_id,
                    "wallet_address": wallet_address,
                },
            )
        user_total = projected_user

    remaining_market = None
    remaining_user = None
    if market_total is not None:
        remaining_market = max(0.0, settings.max_market_stake_zen - market_total)
    if user_total is not None:
        remaining_user = max(0.0, settings.max_user_stake_per_market_zen - user_total)
    return market_total, user_total, remaining_market, remaining_user


@router.post("/pricing/quote", response_model=schemas.PricingQuoteResponse, tags=["pricing"])
async def pricing_quote(
    payload: schemas.PricingQuoteRequest,
    session: AsyncSession = Depends(get_session),
) -> schemas.PricingQuoteResponse:
    """Generate a signed quote bound to stake, FX, outcome, and expiry."""

    now = datetime.now(tz=UTC)
    user_id = payload.user_id or payload.wallet_address
    if payload.stake_zen > settings.max_stake_zen:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "stake_above_cap",
                "stake_zen": float(payload.stake_zen),
                "max_stake_zen": settings.max_stake_zen,
            },
        )
    ticket_size_wei = int(settings.ticket_size_wei)
    stake_wei = _to_wei_amount(payload.stake_zen)
    if stake_wei != ticket_size_wei:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"stake_mismatch_expected_{ticket_size_wei}",
        )
    if payload.market_id:
        market_record = await repository_async.get_market_by_event_id(session, payload.market_id)
        if market_record and (
            market_record.status
            in {shared_models.MarketStatusEnum.SETTLED.value, shared_models.MarketStatusEnum.CANCELLED.value}
            or market_record.resolved_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Market is settled; new quotes are disabled",
            )
        if market_record:
            _assert_commits_allowed(market_record, now, session)
    # Auto-deploy on first quote if a market address is missing.
    ensured_market_address: str | None = (payload.market_address or "") or None
    if payload.market_id and not ensured_market_address:
        market_record = await repository_async.get_market_by_event_id(session, payload.market_id)
        ensured_market_address = getattr(market_record, "market_address", None)
    if payload.market_id and not ensured_market_address:
        from app.routes.trade import _ensure_market_or_create

        _, ensured_market_address, _ = await _ensure_market_or_create(
            session, payload.market_id, payload.market_address
        )
    try:
        fx_quote = await fetch_fx_quote(settings)
        if fx_quote.stale:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "fx_stale",
                    "message": "FX price stale",
                    "fx_received_at": fx_quote.received_at.isoformat() if fx_quote.received_at else None,
                },
            )
        zen_usd = float(fx_quote.zen_usd) if fx_quote.zen_usd is not None else None
        fx_received_at = fx_quote.received_at
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        ) from exc

    market_total = None
    user_total = None
    user_remaining = None
    market_remaining = None
    if payload.market_id:
        market_total, user_total, market_remaining, user_remaining = await _enforce_caps(
            session,
            stake_zen=payload.stake_zen,
            market_id=payload.market_id,
            wallet_address=payload.wallet_address,
            include_stake=True,
        )

    if zen_usd is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        )
    if settings.pricing_chain_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "pricing_chain_missing", "message": "Pricing chain id not configured"},
        )

    zen_usd_scaled = _scale_fx_value(zen_usd)
    engine = PricingEngine(settings)
    try:
        quote = engine.quote(Decimal(str(payload.stake_zen)), Decimal(str(zen_usd)))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        hedge_zen = Decimal(str(quote.hedge_usdc)) / Decimal(str(quote.zen_usd))
        payout_zen = (
            Decimal(str(quote.refund_zen)) + hedge_zen * Decimal(str(quote.displayed_odds_multiplier))
        ).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"payout_compute_failed:{exc}"
        ) from exc

    expires_at = datetime.now(tz=UTC) + timedelta(seconds=settings.pricing_quote_ttl_seconds)
    expiry_ts = int(expires_at.timestamp())
    quote_id = token_hex(32)
    if settings.pricing_signer_private_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "pricing_signer_unavailable", "message": "Pricing signer unavailable"},
            headers=None,
        )
    raw_signer_key = settings.pricing_signer_private_key
    signer_key: str | None
    if isinstance(raw_signer_key, SecretStr):
        signer_key = raw_signer_key.get_secret_value()
    else:
        signer_key = cast(str | None, raw_signer_key)
    signer_account = await asyncio.to_thread(load_account, signer_key)
    signature: str | None = None
    signer_address: str | None = None
    if ensured_market_address:
        try:
            digest = build_quote_digest(
                settings.pricing_chain_id,
                ensured_market_address,
                payload.wallet_address,
                int(payload.outcome_id),
                stake_wei,
                zen_usd_scaled,
                expiry_ts,
                quote_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        message = encode_defunct(hexstr=digest.hex())
        signed = Account.sign_message(message, signer_account.key)
        signature = signed.signature.hex()
        signer_address = signer_account.address

    quote = quote.model_copy(
        update={
            "max_stake_zen": settings.max_stake_zen,
            "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen if payload.market_id else None,
            "max_market_stake_zen": settings.max_market_stake_zen if payload.market_id else None,
            "remaining_user_stake_zen": user_remaining,
            "remaining_market_stake_zen": market_remaining,
            "stake_wei": stake_wei,
            "zen_usd_scaled": zen_usd_scaled,
            "quote_id": quote_id,
            "expires_at": expires_at,
            "expiry_ts": expiry_ts,
            "fx_stale": False,
            "fx_received_at": fx_received_at,
            "signature": signature,
            "signer": signer_address,
            "market_id": payload.market_id,
            "user_id": user_id,
            "wallet_address": payload.wallet_address,
            "outcome_id": payload.outcome_id,
            "market_address": ensured_market_address,
            "chain_id": settings.pricing_chain_id,
            "payout_zen": payout_zen,
        }
    )
    quote_payload = quote.model_dump(mode="json")
    try:
        await repository_async.create_quote(
            session,
            {
                "quote_id": quote_id,
                "status": models.QuoteStatusEnum.ISSUED.value,
                "payload": quote_payload,
                "stake_zen": Decimal(str(quote.stake_zen)),
                "stake_wei": stake_wei,
                "fx_scaled": zen_usd_scaled,
                "zen_usd": quote.zen_usd,
                "market_id": payload.market_id,
                "market_address": ensured_market_address,
                "user_id": user_id,
                "wallet_address": payload.wallet_address,
                "outcome_id": quote.outcome_id,
                "chain_id": settings.pricing_chain_id,
                "expires_at": expires_at,
            },
        )
        await session.flush()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive log
        log_event(
            logger,
            logging.ERROR,
            event="pricing.quote.persist_failed",
            message="failed to persist issued quote",
            quote_id=quote_id,
            error=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Quote persistence failed") from exc

    log_event(
        logger,
        logging.INFO,
        event="pricing.quote",
        message="pricing quote generated",
        stake_zen=payload.stake_zen,
        zen_usd=zen_usd,
        total_monetisation=str(quote.total_monetization),
        market_total=market_total,
        user_total=user_total,
        quote_id=quote_id,
        market_id=payload.market_id,
        user_id=payload.user_id,
    )
    PRICING_COUNTER.labels(event="issue", result="ok").inc()
    return quote


@router.post("/pricing/preview", response_model=schemas.PricingQuoteResponse, tags=["pricing"])
async def pricing_quote_preview(
    payload: schemas.PricingQuoteRequest,
    session: AsyncSession = Depends(get_session),
) -> schemas.PricingQuoteResponse:
    """Return an unsigned, non-persistent preview quote (no market creation, no signature)."""

    # No creation here; best-effort fetch of existing market address.
    now = datetime.now(tz=UTC)
    user_id = payload.user_id or payload.wallet_address
    ticket_size_wei = int(settings.ticket_size_wei)
    stake_wei = _to_wei_amount(payload.stake_zen)
    if stake_wei != ticket_size_wei:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"stake_mismatch_expected_{ticket_size_wei}",
        )
    market_record = None
    if payload.market_id:
        market_record = await repository_async.get_market_by_event_id(session, payload.market_id)
        if market_record:
            _assert_commits_allowed(market_record, now, session)
    market_address: str | None = payload.market_address or None
    if payload.market_id and not market_address and market_record:
        market_address = getattr(market_record, "market_address", None)
    try:
        fx_quote = await fetch_fx_quote(settings)
        if fx_quote.stale:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "fx_stale",
                    "message": "FX price stale",
                    "fx_received_at": fx_quote.received_at.isoformat() if fx_quote.received_at else None,
                },
            )
        zen_usd = float(fx_quote.zen_usd) if fx_quote.zen_usd is not None else None
        fx_received_at = fx_quote.received_at
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        ) from exc

    market_total = None
    user_total = None
    user_remaining = None
    market_remaining = None
    if payload.market_id:
        market_total, user_total, market_remaining, user_remaining = await _enforce_caps(
            session,
            stake_zen=payload.stake_zen,
            market_id=payload.market_id,
            wallet_address=payload.wallet_address,
            include_stake=True,
        )

    if zen_usd is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        )
    if settings.pricing_chain_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "pricing_chain_missing", "message": "Pricing chain id not configured"},
        )

    stake_wei = _to_wei_amount(payload.stake_zen)
    zen_usd_scaled = _scale_fx_value(zen_usd)
    engine = PricingEngine(settings)
    try:
        quote = engine.quote(Decimal(str(payload.stake_zen)), Decimal(str(zen_usd)))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    try:
        hedge_zen = Decimal(str(quote.hedge_usdc)) / Decimal(str(quote.zen_usd))
        payout_zen = (
            Decimal(str(quote.refund_zen)) + hedge_zen * Decimal(str(quote.displayed_odds_multiplier))
        ).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
    except Exception:
        payout_zen = Decimal(str(payload.stake_zen))

    # Preview response mirrors the signed payload but omits signature/persistence/expiry.
    expires_at = datetime.now(tz=UTC) + timedelta(seconds=settings.pricing_quote_ttl_seconds)
    expiry_ts = int(expires_at.timestamp())
    return quote.model_copy(
        update={
            "max_stake_zen": settings.max_stake_zen,
            "max_user_stake_per_market_zen": settings.max_user_stake_per_market_zen if payload.market_id else None,
            "max_market_stake_zen": settings.max_market_stake_zen if payload.market_id else None,
            "remaining_user_stake_zen": user_remaining,
            "remaining_market_stake_zen": market_remaining,
            "stake_wei": stake_wei,
            "zen_usd_scaled": zen_usd_scaled,
            "quote_id": None,
            "expires_at": expires_at,
            "expiry_ts": expiry_ts,
            "fx_stale": False,
            "fx_received_at": fx_received_at,
            "signature": None,
            "signer": None,
            "market_id": payload.market_id,
            "user_id": user_id,
            "wallet_address": payload.wallet_address,
            "outcome_id": payload.outcome_id,
            "market_address": market_address,
            "chain_id": settings.pricing_chain_id,
            "payout_zen": payout_zen,
        }
    )


@router.post("/pricing/submit", response_model=schemas.PricingSubmitResponse, tags=["pricing"])
async def pricing_submit(
    payload: schemas.PricingSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> schemas.PricingSubmitResponse:
    """Validate and mark a quote as consumed, re-checking FX drift if requested."""

    quote = payload.quote
    now = datetime.now(tz=UTC)

    def _as_aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=UTC)
        return dt

    if settings.pricing_chain_id is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pricing chain id not configured")
    if quote.wallet_address is None or quote.market_address is None or quote.outcome_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wallet_address, market_address, and outcome_id are required for signed quotes",
        )

    raw_signer_key = settings.pricing_signer_private_key
    signer_key: str | None
    if isinstance(raw_signer_key, SecretStr):
        signer_key = raw_signer_key.get_secret_value()
    else:
        signer_key = cast(str | None, raw_signer_key)
    signer_account = await asyncio.to_thread(load_account, signer_key) if signer_key else None
    if signer_account is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pricing signer unavailable")

    if not quote.quote_id:
        PRICING_COUNTER.labels(event="submit", result="missing").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote not found or expired")
    quote_id = quote.quote_id
    stmt = select(models.Quote).where(models.Quote.quote_id == quote_id).with_for_update()
    db_quote = (await session.execute(stmt)).scalar_one_or_none()
    if db_quote is None:
        PRICING_COUNTER.labels(event="submit", result="missing").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote not found or expired")
    if db_quote.status == models.QuoteStatusEnum.CONSUMED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quote already consumed")
    db_expires_at = _as_aware(cast(datetime | None, getattr(db_quote, "expires_at", None)))
    if db_quote.status == models.QuoteStatusEnum.EXPIRED.value or (db_expires_at and db_expires_at <= now):
        db_quote.status = models.QuoteStatusEnum.EXPIRED.value
        await session.flush()
        PRICING_COUNTER.labels(event="submit", result="expired").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote expired")
    quote_expires_at = _as_aware(quote.expires_at)
    if quote_expires_at and quote_expires_at <= now:
        db_quote.status = models.QuoteStatusEnum.EXPIRED.value
        await session.flush()
        PRICING_COUNTER.labels(event="submit", result="expired").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote expired")
    if db_quote.wallet_address and quote.wallet_address:
        if db_quote.wallet_address.lower() != quote.wallet_address.lower():
            PRICING_COUNTER.labels(event="submit", result="wallet_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote wallet mismatch")
    if db_quote.market_id and quote.market_id and db_quote.market_id != quote.market_id:
        PRICING_COUNTER.labels(event="submit", result="market_id_mismatch").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote market id mismatch")
    if db_quote.market_address and quote.market_address:
        if db_quote.market_address.lower() != quote.market_address.lower():
            PRICING_COUNTER.labels(event="submit", result="market_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote market mismatch")
    if db_quote.outcome_id is not None and quote.outcome_id is not None:
        if db_quote.outcome_id != quote.outcome_id:
            PRICING_COUNTER.labels(event="submit", result="outcome_mismatch").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote outcome mismatch")

    expiry_reference = quote_expires_at or db_expires_at or now
    expiry_ts = quote.expiry_ts or int(expiry_reference.timestamp())
    quote.expiry_ts = expiry_ts
    stake_wei = quote.stake_wei
    zen_usd_scaled = quote.zen_usd_scaled
    recalculated_stake = _to_wei_amount(quote.stake_zen)
    recalculated_fx = _scale_fx_value(quote.zen_usd)
    if recalculated_stake != stake_wei or recalculated_fx != zen_usd_scaled:
        PRICING_COUNTER.labels(event="submit", result="scaled_mismatch").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote fields do not match scaled values")
    if not quote.signature:
        try:
            digest = build_quote_digest(
                settings.pricing_chain_id,
                quote.market_address,
                quote.wallet_address,
                int(quote.outcome_id),
                stake_wei,
                zen_usd_scaled,
                expiry_ts,
                quote_id,
            )
            signed = Account.sign_message(encode_defunct(hexstr=digest.hex()), signer_account.key)
            quote.signature = signed.signature.hex()
            quote.signer = signer_account.address
        except Exception as exc:
            PRICING_COUNTER.labels(event="submit", result="bad_signature").inc()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid signature: {exc}") from exc
    try:
        digest = build_quote_digest(
            settings.pricing_chain_id,
            quote.market_address,
            quote.wallet_address,
            int(quote.outcome_id),
            stake_wei,
            zen_usd_scaled,
            expiry_ts,
            quote_id,
        )
        recovered = Account.recover_message(encode_defunct(hexstr=digest.hex()), signature=quote.signature)
    except Exception as exc:
        PRICING_COUNTER.labels(event="submit", result="bad_signature").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid signature: {exc}") from exc
    if recovered.lower() != signer_account.address.lower():
        PRICING_COUNTER.labels(event="submit", result="signer_mismatch").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote signer mismatch")
    if db_quote.stake_wei != stake_wei or db_quote.fx_scaled != zen_usd_scaled:
        PRICING_COUNTER.labels(event="submit", result="payload_mismatch").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quote payload mismatch with ledger")

    current_fx: Decimal | None = None
    if payload.max_fx_diff_percent is not None:
        try:
            fx_quote = await fetch_fx_quote(settings)
            if fx_quote.zen_usd is not None:
                current_fx = fx_quote.zen_usd
            if fx_quote.stale:
                PRICING_COUNTER.labels(event="submit", result="fx_stale").inc()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": "fx_stale",
                        "message": "FX price stale during submit",
                        "fx_received_at": fx_quote.received_at.isoformat() if fx_quote.received_at else None,
                    },
                )
            fx_diff_percent = (
                (abs(current_fx - quote.zen_usd) / quote.zen_usd * Decimal("100"))
                if current_fx is not None and quote.zen_usd
                else Decimal("0")
            )
            if current_fx is None:
                PRICING_COUNTER.labels(event="submit", result="fx_missing").inc()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"error": "fx_missing", "message": "FX check failed: missing price"},
                )
            if fx_diff_percent > payload.max_fx_diff_percent:
                PRICING_COUNTER.labels(event="submit", result="fx_drift").inc()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"FX drift {fx_diff_percent:.4f}% exceeds bound {payload.max_fx_diff_percent}%",
                )
        except HTTPException:
            raise
        except Exception as exc:
            PRICING_COUNTER.labels(event="submit", result="fx_error").inc()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "fx_check_failed", "message": f"FX check failed: {exc}"},
            ) from exc
    else:
        current_fx = quote.zen_usd
    market_id_for_caps = db_quote.market_id
    if db_quote.market_id is not None:
        quote.market_id = db_quote.market_id

    await _enforce_caps(
        session,
        stake_zen=quote.stake_zen,
        market_id=market_id_for_caps,
        wallet_address=quote.wallet_address,
        exclude_quote=db_quote,
        include_stake=True,
        statuses={
            models.QuoteStatusEnum.ISSUED.value,
            models.QuoteStatusEnum.CONSUMED.value,
        },
    )

    db_quote.payload = quote.model_dump(mode="json")
    await repository_async.mark_quote_status(
        session,
        db_quote,
        models.QuoteStatusEnum.CONSUMED,
        consumed_at=now,
    )
    await session.flush()
    PRICING_COUNTER.labels(event="submit", result="ok").inc()
    log_event(
        logger,
        logging.INFO,
        event="pricing.submit",
        message="pricing quote submitted",
        quote_id=quote.quote_id,
        market_id=quote.market_id,
        user_id=quote.user_id,
        outcome_id=quote.outcome_id,
        stake_zen=float(quote.stake_zen),
        zen_usd=float(quote.zen_usd),
    )

    return schemas.PricingSubmitResponse(
        quote=quote,
        current_fx=current_fx if current_fx is not None else quote.zen_usd,
        valid=True,
    )


@router.get("/pricing/quotes/{quote_id}", response_model=schemas.QuoteRecord, tags=["pricing"])
async def pricing_quote_state(quote_id: str, session: AsyncSession = Depends(get_session)) -> schemas.QuoteRecord:
    record = await repository_async.get_quote(session, quote_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quote_not_found")
    return schemas.QuoteRecord.model_validate(record)


@router.get("/pricing/fx", response_model=schemas.FxQuoteResponse, tags=["pricing"])
async def pricing_fx() -> schemas.FxQuoteResponse:
    try:
        fx_quote = await fetch_fx_quote(settings, use_cache_on_error=False)
        if fx_quote.stale:
            log_event(
                logger,
                logging.WARNING,
                event="pricing.fx.stale",
                message="FX feed stale",
                fx_received_at=fx_quote.received_at.isoformat() if fx_quote.received_at else None,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "fx_stale",
                    "message": "FX price stale",
                    "fx_received_at": fx_quote.received_at.isoformat() if fx_quote.received_at else None,
                },
            )
        return fx_quote
    except httpx.HTTPError as exc:
        log_event(
            logger,
            logging.WARNING,
            event="pricing.fx.error",
            message="failed to fetch FX feed",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive catch for malformed payloads
        log_event(
            logger,
            logging.WARNING,
            event="pricing.fx.error",
            message="unexpected FX parsing error",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "fx_unavailable", "message": "FX price unavailable"},
        ) from exc
