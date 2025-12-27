"""Utilities to construct proof receipt responses with cached fallback data."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from app import models, schemas
from shared import models as shared_models


def _normalize_bigint(value: Any) -> str | None:
    """Coerce various numeric types to a decimal string representation."""

    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return str(int(value))
        return str(int(value))
    except (TypeError, ValueError, OverflowError):
        try:
            return str(value)
        except (TypeError, ValueError):
            return None


def _cached_value(cached: dict[str, Any] | None, *keys: str) -> Any:
    """Safely pull a value from a cached dict, tolerating missing/invalid types."""

    if not isinstance(cached, dict):
        return None
    for key in keys:
        if key in cached:
            return cached[key]
    return None


def _cached_public_signals(cached: dict[str, Any] | None) -> list[str] | None:
    """Return a normalized list of public signals from cached proof data."""

    signals = _cached_value(cached, "public_signals", "publicSignals")
    if isinstance(signals, list):
        try:
            return [str(entry) for entry in signals]
        except Exception:
            return None
    return None


def _normalize_root_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, (bytes, bytearray)):
            return int.from_bytes(value, "big") if value else None
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if cleaned.startswith("0x"):
                cleaned = cleaned[2:]
                return int(cleaned or "0", 16)
            return int(cleaned)
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_public_signals(signals: list[Any] | None) -> dict[str, str | None]:
    """Map public signals to named fields we expose in API responses."""

    parsed: dict[str, str | None] = {
        "merkle_root": None,
        "market_id": None,
        "winning_outcome_id": None,
        "total_escrow": None,
        "total_liability": None,
        "rake_bps": None,
        "pool_total_yes": None,
        "pool_total_no": None,
        "circuit_hash": None,
    }
    if not signals:
        return parsed
    try:
        normalized = [str(entry) for entry in signals]
    except (TypeError, ValueError):
        return parsed
    fields = [
        "merkle_root",
        "market_id",
        "winning_outcome_id",
        "total_escrow",
        "total_liability",
        "rake_bps",
        "pool_total_yes",
        "pool_total_no",
        "circuit_hash",
    ]
    for index, key in enumerate(fields):
        if index < len(normalized):
            parsed[key] = normalized[index]
    return parsed


def _coalesce(*values: Any) -> Any:
    """Return the first non-empty value."""

    for value in values:
        if value not in (None, ""):
            return value
    return None


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


def build_proof_receipt_model(
    receipt: shared_models.SettlementReceipt,
    settlement: shared_models.Settlement | None,
    market: shared_models.Market | None,
    cached: dict[str, Any] | None,
) -> schemas.ProofReceipt:
    """Compose a ProofReceipt from DB rows while preferring cached proof payloads."""

    cached_signals = _cached_public_signals(cached)
    raw_signals = receipt.public_signals
    signals: list[str] | None = None
    if isinstance(raw_signals, (list, tuple)):
        signals = [str(value) for value in raw_signals]
    elif cached_signals:
        signals = cached_signals
    else:
        signals = []
    parsed_signals = _parse_public_signals(signals)

    settlement_root = getattr(settlement, "merkle_root", None) if settlement is not None else None
    if _is_empty_hex(settlement_root):
        settlement_root = None
    merkle_root = _coalesce(
        _cached_value(cached, "merkleRoot"),
        parsed_signals.get("merkle_root"),
        settlement_root,
    )
    batch_index = None
    batch_index_raw = getattr(receipt, "batch_index", None)
    if batch_index_raw is not None:
        try:
            batch_index = int(str(batch_index_raw))
        except (TypeError, ValueError):
            batch_index = None
    pool_total_yes = _normalize_bigint(
        _coalesce(
            getattr(settlement, "pool_total_yes", None) if settlement is not None else None,
            parsed_signals.get("pool_total_yes"),
            _cached_value(cached, "poolTotalYes"),
        )
    )
    pool_total_no = _normalize_bigint(
        _coalesce(
            getattr(settlement, "pool_total_no", None) if settlement is not None else None,
            parsed_signals.get("pool_total_no"),
            _cached_value(cached, "poolTotalNo"),
        )
    )
    total_escrow = _normalize_bigint(
        _coalesce(
            getattr(settlement, "total_escrow", None) if settlement is not None else None,
            parsed_signals.get("total_escrow"),
            _cached_value(cached, "totalEscrow"),
        )
    )
    total_liability = _normalize_bigint(
        _coalesce(
            getattr(settlement, "total_liability", None) if settlement is not None else None,
            parsed_signals.get("total_liability"),
            _cached_value(cached, "totalLiability"),
        )
    )

    winning_outcome_raw = _coalesce(
        getattr(settlement, "winning_outcome_id", None) if settlement is not None else None,
        parsed_signals.get("winning_outcome_id"),
        _cached_value(cached, "winningOutcomeId"),
    )
    try:
        winning_outcome_id = int(winning_outcome_raw) if winning_outcome_raw not in (None, "") else None
    except (TypeError, ValueError):
        winning_outcome_id = None

    rake_bps_raw = _coalesce(
        getattr(settlement, "rake_bps", None) if settlement is not None else None,
        parsed_signals.get("rake_bps"),
        _cached_value(cached, "rakeBps"),
    )
    try:
        rake_bps = int(rake_bps_raw) if rake_bps_raw not in (None, "") else None
    except (TypeError, ValueError):
        rake_bps = None

    circuit_hash = _coalesce(
        receipt.circuit_hash,
        settlement.circuit_hash if settlement is not None else None,
        parsed_signals.get("circuit_hash"),
        _cached_value(cached, "circuit_hash", "circuitHash"),
    )
    proof_hash = _coalesce(receipt.proof_hash, _cached_value(cached, "proof_hash", "proofHash"))
    proof_value = _cached_value(cached, "proof")
    generated_at = _coalesce(receipt.generated_at, _cached_value(cached, "generated_at", "generatedAt"))
    condition_id = _coalesce(
        getattr(market, "condition_id", None) if market is not None else None,
        _cached_value(cached, "conditionId"),
    )
    if isinstance(condition_id, str):
        condition_id = condition_id.lower()
    if batch_index is None and settlement is not None:
        batch_roots = getattr(settlement, "batch_roots", None)
        if isinstance(batch_roots, (list, tuple)) and merkle_root is not None and not _is_empty_hex(merkle_root):
            merkle_root_int = _normalize_root_int(merkle_root)
            if merkle_root_int is not None:
                for index, root_value in enumerate(batch_roots):
                    root_int = _normalize_root_int(root_value)
                    if root_int is not None and root_int == merkle_root_int:
                        batch_index = index
                        break
    if batch_index is None and not _is_empty_hex(merkle_root) and settlement is not None:
        batch_roots = getattr(settlement, "batch_roots", None)
        if not batch_roots:
            batch_index = 0
    if batch_index is None:
        cached_batch_index = _cached_value(cached, "batchIndex", "batch_index")
        if cached_batch_index is not None:
            try:
                batch_index = int(cached_batch_index)
            except (TypeError, ValueError):
                batch_index = None
    market_address = _coalesce(
        receipt.market_address, getattr(market, "market_address", None) if market is not None else None
    ) or _cached_value(cached, "marketAddress")
    market_id_value = _coalesce(
        receipt.market_id,
        parsed_signals.get("market_id"),
        _cached_value(cached, "marketId"),
    )
    try:
        market_id_int = int(market_id_value) if market_id_value is not None else None
    except (TypeError, ValueError):
        try:
            market_id_int = int(receipt.market_id) if receipt.market_id is not None else None
        except Exception:
            market_id_int = None

    winning_pool = None
    if winning_outcome_id in (0, 1):
        winning_pool = pool_total_yes if winning_outcome_id == 0 else pool_total_no
    total_pool = total_escrow
    if total_pool is None and pool_total_yes is not None and pool_total_no is not None:
        try:
            total_pool = str(int(pool_total_yes) + int(pool_total_no))
        except Exception:
            total_pool = None

    settlement_tx_hash = _coalesce(
        getattr(settlement, "settlement_tx_hash", None) if settlement is not None else None,
        _cached_value(cached, "settlement_tx_hash", "settlementTxHash", "txHash", "transactionHash"),
    )

    receipt_payload = {
        "request_id": receipt.request_id,
        "market_id": market_id_int,
        "event_id": getattr(market, "event_id", None),
        "condition_id": condition_id,
        "market_address": market_address,
        "settlement_tx_hash": settlement_tx_hash,
        "proof_hash": proof_hash,
        "prover_version": receipt.prover_version or _cached_value(cached, "prover_version", "proverVersion"),
        "circuit_hash": circuit_hash,
        "generated_at": generated_at,
        "proof": proof_value,
        "public_signals": [str(value) for value in (signals or [])],
        "merkle_root": merkle_root,
        "batch_index": batch_index,
        "total_escrow": total_escrow,
        "total_liability": total_liability,
        "rake_bps": rake_bps,
        "winning_outcome_id": winning_outcome_id,
        "pool_total_yes": pool_total_yes,
        "pool_total_no": pool_total_no,
        "winning_pool": winning_pool,
        "total_pool": total_pool,
    }

    return schemas.ProofReceipt.model_validate(receipt_payload)


async def load_proof_receipts(
    settlements: Iterable[shared_models.Settlement],
    receipts: Iterable[shared_models.SettlementReceipt],
    markets: Iterable[models.Market],
    cached_receipts: dict[str, Any] | None,
) -> list[schemas.ProofReceipt]:
    market_map: dict[int, models.Market] = {}
    for market_record in markets:
        if market_record.id is None:
            continue
        market_map[int(market_record.id)] = market_record

    settlement_map: dict[int, shared_models.Settlement] = {}
    for settlement_record in settlements:
        try:
            if settlement_record.market_id is not None:
                settlement_map[int(settlement_record.market_id)] = settlement_record
        except (TypeError, ValueError):
            continue

    cached_by_request: dict[str, Any] = {}
    if isinstance(cached_receipts, dict):
        receipts_array = cached_receipts.get("receipts")
        if isinstance(receipts_array, Iterable):
            for record in receipts_array:
                request_id = None
                if isinstance(record, dict):
                    request_id = cast(str | None, record.get("request_id") or record.get("requestId"))
                if request_id:
                    cached_by_request[request_id] = record

    models_list: list[schemas.ProofReceipt] = []
    for receipt in receipts:
        cached_record = cached_by_request.get(receipt.request_id)
        market: shared_models.Market | None = None
        settlement: shared_models.Settlement | None = None
        try:
            if receipt.market_id is not None:
                market = market_map.get(int(receipt.market_id))
                settlement = settlement_map.get(int(receipt.market_id))
        except (TypeError, ValueError):
            market = None
            settlement = None
        model = build_proof_receipt_model(receipt, settlement, market, cached_record)
        created_at = getattr(receipt, "created_at", None)
        if model.generated_at is None and isinstance(created_at, (int, float)):
            model.generated_at = datetime.fromtimestamp(created_at, tz=UTC)
        elif model.generated_at is None and isinstance(created_at, datetime):
            model.generated_at = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
        models_list.append(model)
    return models_list
