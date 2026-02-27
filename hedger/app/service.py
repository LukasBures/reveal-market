from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from redis.asyncio import Redis
from tenacity import RetryError

from .bet_processor_zen import BetProcessorZen
from .bridge import BridgeClient
from .clob import ClobConfig, HedgerClob
from .config import Settings
from .exposure import ExposureLedger
from .fx import FxOracle
from .local_logging import log_event
from .locks import RedisLockManager
from .metrics import (
    HEDGE_EXECUTIONS,
    record_event_lag,
    record_hedge_decision,
    record_risk_breach,
    update_hot_wallet_balance,
)
from .pricing_engine import PricingEngine
from .risk import RiskEngine, RiskLimits
from .settlement import SettlementCoordinator
from .storage import HedgerRepository
from .treasury_manager import TreasuryManager
from .types import CommitEvent, HedgeInstruction, MarketExposureSnapshot, OutcomeSide, RiskBreach, RiskSeverity
from .wallet import HedgerWallet, WalletConfig

logger = logging.getLogger("reveal_market.hedger.service")


class HedgerService:
    """Coordinates exposure ingestion, hedging, settlements, and float controls."""

    def __init__(self, settings: Settings):
        limits = RiskLimits(
            max_global_exposure_usd=settings.risk_max_global_exposure_usd,
            max_per_market_usd=settings.risk_max_per_market_usd,
            coverage_ratio_target=settings.risk_coverage_ratio_target,
            float_min_zen=settings.float_min_zen,
        )
        self.settings = settings
        self.repository = HedgerRepository(settings.database_url)
        self.risk_engine = RiskEngine(limits)
        self._category_limits = self._parse_category_limits(settings.risk_category_limits)
        self.redis: Redis | None = None
        self.fx_oracle = FxOracle(
            feed_url=settings.fx_feed_url,
            feed_alt_url=settings.fx_feed_alt_url,
            haircut_bps=settings.fx_haircut_bps,
            timeout_seconds=settings.fx_timeout_seconds,
            max_age_seconds=settings.fx_max_age_seconds,
            retry_backoff_seconds=settings.polymarket_retry_backoff_seconds,
            fallback_zen_usd=settings.fx_fallback_price,
        )
        self.pricing_engine = PricingEngine(
            haircut_percent=settings.haircut_percent,
            worsen_percent=settings.worsen_percent,
            rake_percent=settings.rake_percent,
        )
        self.treasury = TreasuryManager(lp_share_percent=settings.lp_share_percent)
        self.bet_processor = BetProcessorZen(self.pricing_engine, self.treasury)
        self.bridge_client = BridgeClient(
            base_url=settings.bridge_endpoint,
            timeout_seconds=settings.polymarket_timeout_seconds,
            retry_attempts=settings.polymarket_retry_attempts,
            retry_backoff_seconds=settings.polymarket_retry_backoff_seconds,
        )
        if not self.settings.hedger_private_key:
            log_event(
                logger,
                logging.ERROR,
                event="hedger.config.missing_wallet",
                message="hedger private key missing; running in read-only mode",
            )
            self.settings = self.settings.model_copy(update={"admin_read_only": True}, deep=True)
        self.wallet: HedgerWallet | None = None
        self.clob: HedgerClob | None = None
        if self.settings.hedger_private_key:
            wallet_cfg = WalletConfig(
                rpc_url=self.settings.polygon_rpc_url,
                chain_id=self.settings.polygon_chain_id,
                private_key=self.settings.hedger_private_key,
                usdc_address=self.settings.usdc_address,
                usdc_decimals=self.settings.usdc_decimals,
                polymarket_exchange=self.settings.polymarket_exchange,
                auto_approve=self.settings.auto_approve,
            )
            self.wallet = HedgerWallet(wallet_cfg)
            if not (
                self.settings.polymarket_api_key
                and self.settings.polymarket_api_secret
                and self.settings.polymarket_api_passphrase
            ):
                log_event(
                    logger,
                    logging.ERROR,
                    event="hedger.config.missing_clob_creds",
                    message="polymarket clob api credentials missing; running in read-only mode",
                )
                self.settings = self.settings.model_copy(update={"admin_read_only": True}, deep=True)
            if (
                self.settings.polymarket_api_key
                and self.settings.polymarket_api_secret
                and self.settings.polymarket_api_passphrase
            ):
                clob_cfg = ClobConfig(
                    host=self.settings.polymarket_clob_base,
                    chain_id=self.settings.polygon_chain_id,
                    private_key=str(self.settings.hedger_private_key),
                    api_key=self.settings.polymarket_api_key,
                    api_secret=self.settings.polymarket_api_secret,
                    api_passphrase=self.settings.polymarket_api_passphrase,
                    funder=self.wallet.address,
                )
                self.clob = HedgerClob(clob_cfg)
        self.exposure_ledger = ExposureLedger(
            fx_oracle=self.fx_oracle,
            limits=limits,
            risk_engine=self.risk_engine,
            repository=self.repository,
        )
        self.settlement = SettlementCoordinator(
            base_url=settings.prover_base_url,
            timeout_seconds=settings.prover_timeout_seconds,
            shared_secret=settings.prover_shared_secret,
            repository=self.repository,
        )
        self.lock_manager: RedisLockManager | None = None
        self._noop_lock = self._noop_async_lock()
        self._health_snapshot: dict[str, Any] | None = None
        self._health_snapshot_ts: datetime | None = None
        self._redis_available: bool | None = None

    async def startup(self) -> None:
        if self.settings.run_migrations_on_startup:
            await self.repository.create_schema()
        try:
            self.redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
            self.lock_manager = RedisLockManager(
                self.redis, self.settings.redis_lock_ttl_seconds, self.settings.redis_idempotency_ttl_seconds
            )
            self._redis_available = True
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.redis.unavailable",
                message="redis unavailable; using in-memory locks only",
                error=str(exc),
            )
            if self.settings.redis_required:
                log_event(
                    logger,
                    logging.ERROR,
                    event="hedger.redis.required",
                    message="redis required but unavailable; switching to read-only mode",
                    error=str(exc),
                )
                self.settings = self.settings.model_copy(update={"admin_read_only": True}, deep=True)
            self.redis = None
            self.lock_manager = RedisLockManager(
                None, self.settings.redis_lock_ttl_seconds, self.settings.redis_idempotency_ttl_seconds
            )
            self._redis_available = False
        try:
            await self.fx_oracle.refresh()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.fx.refresh_failed",
                message="fx refresh failed during startup",
                error=str(exc),
            )
        try:
            await self._hydrate_from_storage()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.hydrate.failed",
                message="failed to hydrate exposure state from storage",
                error=str(exc),
            )
        log_event(
            logger,
            logging.INFO,
            event="hedger.startup",
            message="hedger service initialised",
            redis_url=self.settings.redis_url,
        )

    async def ingest_commit(self, commit: CommitEvent) -> dict[str, Any]:
        if self.settings.admin_read_only:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.read_only",
                message="rejecting commit during read-only mode",
                market_id=commit.market_id,
            )
            return {"status": "rejected", "reason": "read_only"}
        idemp_key = self._build_idempotency_key(commit)
        if self.lock_manager and not await self.lock_manager.claim_idempotency(idemp_key):
            log_event(
                logger,
                logging.INFO,
                event="hedger.commit.duplicate",
                message="commit dropped (idempotency claim failed)",
                market_id=commit.market_id,
                idempotency_key=idemp_key,
            )
            return {"status": "duplicate", "idempotency_key": idemp_key}
        try:
            if await self.repository.commit_exists(idemp_key):
                log_event(
                    logger,
                    logging.INFO,
                    event="hedger.commit.duplicate.db",
                    message="commit dropped (duplicate idempotency key in DB)",
                    market_id=commit.market_id,
                    idempotency_key=idemp_key,
                )
                return {"status": "duplicate", "idempotency_key": idemp_key}
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.db_unavailable",
                message="database unavailable; skipping idempotency check",
                market_id=commit.market_id,
                error=str(exc),
            )

        if self.fx_oracle.stale():
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.fx_stale",
                message="rejecting commit because FX oracle is stale",
                market_id=commit.market_id,
            )
            return {"status": "rejected", "reason": "fx_unavailable"}

        try:
            quote = await self.fx_oracle.get_quote()
        except (RetryError, httpx.HTTPError, InvalidOperation, ValueError) as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.fx_error",
                message="rejecting commit because FX oracle errored",
                market_id=commit.market_id,
                error=str(exc),
            )
            return {"status": "rejected", "reason": "fx_unavailable", "error": str(exc)}
        signed_quote = getattr(commit, "signed_quote", None)
        requires_signed_quote = bool(self.settings.pricing_signer_address)
        if requires_signed_quote and not signed_quote:
            return {"status": "rejected", "reason": "quote_required"}
        if signed_quote:
            valid, reason = await self._validate_signed_quote(commit, signed_quote)
            if not valid:
                return {"status": "rejected", "reason": reason or "invalid_quote"}
        if commit.stake_zen > self.settings.risk_max_commit_zen:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.stake_limit",
                message="rejecting commit because stake exceeds max per-commit limit",
                market_id=commit.market_id,
                stake_zen=str(commit.stake_zen),
                stake_limit=str(self.settings.risk_max_commit_zen),
            )
            return {"status": "rejected", "reason": "stake_limit"}
        try:
            pricing = self.bet_processor.price_bet(commit.stake_zen, quote.zen_usd)
        except ValueError as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.invalid",
                message="pricing engine rejected commit",
                market_id=commit.market_id,
                error=str(exc),
            )
            return {"status": "rejected", "reason": str(exc)}

        if not self.wallet:
            return {"status": "rejected", "reason": "wallet_unavailable"}
        balance_ok, balance = self.wallet.has_sufficient_balance(pricing.hedge_usdc)
        update_hot_wallet_balance(float(balance))
        if not balance_ok:
            return {
                "status": "rejected",
                "reason": "insufficient_usdc",
                "balance_usdc": str(balance),
                "pricing": pricing.model_dump(mode="json"),
            }

        def _commit_lock():
            return self.lock_manager.lock(f"commit:{commit.market_id}") if self.lock_manager else nullcontext()

        try:
            async with _commit_lock():
                snapshot, instruction, breaches = await self.exposure_ledger.preview_commit(
                    commit, stake_usd=pricing.hedge_usdc
                )
                category_breaches = self._check_category_limits(
                    commit.market_id,
                    commit.category,
                    snapshot,
                )
                if category_breaches:
                    breaches.extend(category_breaches)
                    log_event(
                        logger,
                        logging.WARNING,
                        event="hedger.category.limit_exceeded",
                        message="category exposure limit exceeded",
                        market_id=commit.market_id,
                        category=commit.category,
                        limit=category_breaches[0].detail["limit"] if category_breaches[0].detail else None,
                        absolute_usd=category_breaches[0].detail["absolute_usd"]
                        if category_breaches[0].detail
                        else None,
                    )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.preview_failed",
                message="failed to preview commit",
                market_id=commit.market_id,
                error=str(exc),
            )
            return {"status": "rejected", "reason": "commit_failed", "error": str(exc)}

        response: dict[str, Any] = {
            "snapshot": snapshot,
            "hedge_instruction": instruction,
            "breaches": breaches,
            "pricing": pricing.model_dump(mode="json"),
        }
        if breaches:
            for breach in breaches:
                record_risk_breach(str(breach.code), str(breach.severity))

        if instruction:
            record_hedge_decision(instruction.action, instruction.reason)
            hedge_result = await self._execute_hedge(instruction)
            response["hedge_execution"] = hedge_result
            if hedge_result.get("status") == "rejected":
                response["status"] = "rejected"
                response["reason"] = hedge_result.get("reason")
                if not hedge_result.get("reconciled_fill"):
                    return response
                response["status"] = "partial_fill"

        try:
            async with _commit_lock():
                snapshot, _, _ = await self.exposure_ledger.record_commit(
                    commit, idempotency_key=idemp_key, stake_usd=pricing.hedge_usdc, persist=True
                )
                response["snapshot"] = snapshot
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.persist_failed",
                message="failed to persist commit after hedge",
                market_id=commit.market_id,
                error=str(exc),
            )
            response["status"] = "rejected"
            response["reason"] = "commit_failed"
            response["error"] = str(exc)
            return response

        if commit.stream_offset:
            await self.repository.set_replay_offset(self.settings.commit_stream_name, commit.stream_offset)
        return response

    async def _validate_signed_quote(
        self, commit: CommitEvent, quote_payload: Mapping[str, Any] | Any
    ) -> tuple[bool, str | None]:
        """
        If a SignedQuote payload is attached to the commit, ensure it is fresh and matches stake/outcome/fx.
        This mirrors the on-chain digest and prevents hedging against tampered client inputs.
        """

        if hasattr(quote_payload, "model_dump"):
            quote_payload = quote_payload.model_dump()
        market_address = getattr(commit, "market_address", None)
        outcome_id = getattr(commit, "outcome_id", None)
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
            from web3 import Web3
        except ImportError as exc:  # pragma: no cover - runtime dependency guard
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.quote_validation_unavailable",
                message="signature validation skipped (missing web3/eth_account)",
                error=str(exc),
            )
            return True, None

        try:
            stake_wei_raw = quote_payload.get("stake_wei")
            fx_scaled_raw = quote_payload.get("zen_usd_scaled")
            expiry_ts_raw = quote_payload.get("expiry_ts")
            chain_id_raw = quote_payload.get("chain_id")
            if stake_wei_raw is None or fx_scaled_raw is None or expiry_ts_raw is None or chain_id_raw is None:
                raise ValueError("quote_fields_missing")
            stake_wei = int(stake_wei_raw)
            fx_scaled = int(fx_scaled_raw)
            expiry_ts = int(expiry_ts_raw)
            chain_id = int(chain_id_raw)
        except (TypeError, ValueError) as exc:
            logger.debug("quote parse failed", extra={"event": "hedger.commit.quote_parse_failed", "error": str(exc)})
            return False, "quote_fields_invalid"

        # Reject expired quotes before hedging.
        now = datetime.now(UTC).timestamp()
        if expiry_ts <= now:
            return False, "quote_expired"

        # Basic field alignment with the commit.
        if int(commit.stake_zen * Decimal("1e18")) != stake_wei:
            return False, "quote_stake_mismatch"
        quote_market_address = quote_payload.get("market_address")
        if market_address and quote_market_address:
            quote_market_address = str(quote_market_address)
            if market_address.lower() != quote_market_address.lower():
                return False, "quote_market_mismatch"
        if outcome_id is not None and quote_payload.get("outcome_id") is not None:
            if int(outcome_id) != int(quote_payload["outcome_id"]):
                return False, "quote_outcome_mismatch"

        # Mirror the contract digest to verify signature.
        try:
            digest = Web3.solidity_keccak(
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
                    chain_id,
                    Web3.to_checksum_address(quote_payload["market_address"]),
                    Web3.to_checksum_address(quote_payload["wallet_address"]),
                    int(quote_payload["outcome_id"]),
                    stake_wei,
                    fx_scaled,
                    expiry_ts,
                    bytes.fromhex(quote_payload["quote_id"].removeprefix("0x")),
                ],
            )
            recovered = Account.recover_message(
                encode_defunct(hexstr=digest.hex()), signature=quote_payload["signature"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.quote_validation_failed",
                message="signature validation failed",
                error=str(exc),
            )
            return False, "quote_signature_invalid"

        if self.settings.pricing_signer_address and recovered.lower() != self.settings.pricing_signer_address.lower():
            return False, "quote_signer_mismatch"

        # Optional FX drift check: reject if hedger FX differs materially from quote FX.
        try:
            live_quote = await self.fx_oracle.get_quote()
            live_scaled = int((live_quote.zen_usd * Decimal("1e8")).to_integral_value())
            drift_pct = abs(live_scaled - fx_scaled) / fx_scaled * 100 if fx_scaled else 0
            if drift_pct > 5:  # 5% drift guardrail; adjust if needed
                return False, "quote_fx_drift"
        except (RetryError, httpx.HTTPError, InvalidOperation, ValueError) as exc:
            logger.warning(
                "FX drift check skipped — oracle unavailable; accepting quote with stale FX",
                extra={"event": "hedger.commit.quote_fx_invalid", "error": str(exc)},
            )

        return True, None

    async def _execute_hedge(self, instruction: HedgeInstruction) -> dict[str, Any]:
        if self.settings.admin_read_only:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.read_only",
                message="rejecting hedge during read-only mode",
                market_id=instruction.market_id,
            )
            return {"status": "rejected", "reason": "read_only"}
        lock_ctx = self.lock_manager.lock(f"hedge:{instruction.market_id}") if self.lock_manager else self._noop_lock
        async with lock_ctx:
            if not self.wallet:
                log_event(
                    logger,
                    logging.WARNING,
                    event="hedger.wallet.unavailable",
                    message="wallet unavailable; rejecting hedge execution",
                    market_id=instruction.market_id,
                )
                return {"status": "rejected", "reason": "wallet_unavailable"}

            balance_ok, balance = self.wallet.has_sufficient_balance(instruction.size_usd)
            update_hot_wallet_balance(float(balance))
            if not balance_ok:
                return {"status": "rejected", "reason": "insufficient_usdc", "balance_usdc": str(balance)}

            if not self.clob:
                return {"status": "rejected", "reason": "clob_unavailable"}
            approval_tx = self.wallet.ensure_allowance()
            try:
                token_id = instruction.clob_token_id
                if not token_id:
                    return {"status": "rejected", "reason": "clob_token_missing"}
                order_response = self.clob.place_market_order(
                    token_id=str(token_id),
                    amount_usd=instruction.size_usd,
                    action=instruction.action,
                )
            except (RuntimeError, ValueError) as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    event="hedger.hedge.order_failed",
                    message="polymarket clob order failed",
                    market_id=instruction.market_id,
                    error=str(exc),
                )
                return {"status": "rejected", "reason": "order_failed", "error": str(exc)}

            filled_size = self._extract_filled_size(order_response, instruction.size_usd)
            if filled_size is None:
                return {
                    "status": "rejected",
                    "reason": "unparseable_fill",
                    "order": order_response,
                }
            fill_ratio = float(filled_size / instruction.size_usd) if instruction.size_usd else 1.0
            min_fill_ratio = float(self.settings.min_fill_percent) / 100.0
            if filled_size <= 0:
                return {
                    "status": "rejected",
                    "reason": "no_fill",
                    "order": order_response,
                }

        await self.exposure_ledger.register_fill(instruction.market_id, filled_size, is_unwind=instruction.is_unwind)
        await self.repository.record_hedge_instruction(instruction, response_payload=order_response)
        await self.repository.record_audit_log(
            event="hedge_executed",
            actor=None,
            market_id=instruction.market_id,
            payload={
                "action": instruction.action,
                "outcome": instruction.hedge_outcome,
                "size_usd": str(filled_size),
                "reason": instruction.reason,
                "is_unwind": instruction.is_unwind,
            },
        )
        HEDGE_EXECUTIONS.labels(action=instruction.action, outcome=instruction.hedge_outcome).inc()
        log_event(
            logger,
            logging.INFO,
            event="hedger.hedge.executed",
            message="hedge placed on Polymarket",
            market_id=instruction.market_id,
            action=instruction.action,
            size_usd=str(filled_size),
            partial_fill=float(filled_size / instruction.size_usd) if instruction.size_usd else 1.0,
        )
        if fill_ratio < min_fill_ratio:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.hedge.partial_below_threshold",
                message="recorded partial fill below threshold",
                market_id=instruction.market_id,
                action=instruction.action,
                size_usd=str(filled_size),
                required_fill_percent=str(self.settings.min_fill_percent),
            )
            return {
                "status": "rejected",
                "reason": "fill_below_threshold",
                "filled_size_usd": str(filled_size),
                "required_fill_percent": str(self.settings.min_fill_percent),
                "reconciled_fill": True,
                "order": order_response,
                "approval_tx": approval_tx,
            }
        return {
            "order": order_response,
            "filled_size_usd": str(filled_size),
            "approval_tx": approval_tx,
        }

    async def exposures(self) -> list[MarketExposureSnapshot]:
        return await self.exposure_ledger.snapshot()

    async def trigger_settlement(self, market_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if self.settings.admin_read_only:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.read_only",
                message="rejecting settlement during read-only mode",
                market_id=market_id,
            )
            return {"status": "rejected", "reason": "read_only"}
        try:
            return await self.settlement.request_settlement(market_id, dict(payload))
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.settlement.request_failed",
                message="settlement request failed",
                market_id=market_id,
                error=str(exc),
            )
            return {"status": "rejected", "reason": "settlement_failed", "error": str(exc)}

    async def settle_market(self, market_id: str, outcome: OutcomeSide | str) -> dict[str, Any]:
        if isinstance(outcome, OutcomeSide):
            outcome_value = outcome.value
        else:
            outcome_value = outcome
        lock_ctx = self.lock_manager.lock(f"settle:{market_id}") if self.lock_manager else self._noop_lock
        async with lock_ctx:
            if await self.repository.is_market_resolved(market_id):
                return {"status": "already_resolved", "market_id": market_id}

            payload = await self._build_prover_payload(market_id, outcome_value)
            log_event(
                logger,
                logging.INFO,
                event="hedger.settlement.request",
                message="requesting settlement proof",
                market_id=market_id,
                outcome=outcome_value,
                commit_count=len(payload["commits"]),
            )
            try:
                response = await self.settlement.request_settlement(market_id, dict(payload))
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    event="hedger.settlement.failed",
                    message="settlement proof request failed",
                    market_id=market_id,
                    error=str(exc),
                )
                try:
                    await self.repository.record_audit_log(
                        event="settlement_failed",
                        actor="hedger",
                        market_id=market_id,
                        payload={"outcome": outcome_value, "error": str(exc), "error_type": type(exc).__name__},
                    )
                except Exception as db_exc:  # pragma: no cover - best-effort persistence
                    log_event(
                        logger, logging.DEBUG, event="hedger.settlement.audit_persist_failed", error=str(db_exc),
                    )
                return {"status": "rejected", "reason": "settlement_failed", "error": str(exc)}
            await self.repository.record_settlement(
                market_id=market_id,
                outcome=outcome_value,
                proof_payload=response,
                prover_latency_seconds=None,
                submitted_tx=None,
            )
            economics = await self._build_and_persist_economics(market_id, outcome_value)
            await self.repository.mark_market_resolved(market_id, outcome_value)
            await self.exposure_ledger.finalize_market(market_id)
            log_event(
                logger,
                logging.INFO,
                event="hedger.market.resolved",
                message="market marked resolved and exposure cleared",
                market_id=market_id,
                outcome=outcome_value,
            )
            return {"status": "resolved", "payload": payload, "proof": response, "economics": economics}

    async def request_bridge(
        self, direction: str, amount: Decimal, destination: str, *, slippage_bps: int | None = None
    ) -> dict[str, Any]:
        """
        Manually request a bridge transfer. Direction must be `usdc_to_zen` or `zen_to_usdc`.
        """

        slippage = slippage_bps if slippage_bps is not None else self.settings.max_slippage_bps
        idempotency = f"{direction}:{destination}:{amount}"
        if self.settings.admin_read_only:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.read_only",
                message="rejecting bridge during read-only mode",
                direction=direction,
            )
            return {"status": "rejected", "reason": "read_only"}
        if direction == "usdc_to_zen":
            return await self.bridge_client.bridge_to_zen(
                amount, destination, slippage_bps=slippage, idempotency=idempotency
            )
        if direction == "zen_to_usdc":
            return await self.bridge_client.bridge_to_usdc(
                amount, destination, slippage_bps=slippage, idempotency=idempotency
            )
        raise ValueError("direction must be 'usdc_to_zen' or 'zen_to_usdc'")

    async def health(self) -> dict[str, Any]:
        try:
            latest_commit_at = await self.repository.latest_commit_timestamp()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.health.db_failed",
                message="failed to read commit timestamp",
                error=str(exc),
            )
            latest_commit_at = None
        fx_stale = self.fx_oracle.stale()
        if fx_stale:
            try:
                await self.fx_oracle.refresh()
                fx_stale = self.fx_oracle.stale()
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    event="hedger.health.fx_refresh_failed",
                    message="failed to refresh fx quote during health check",
                    error=str(exc),
                )
        balance = None
        if self.wallet:
            try:
                balance = self.wallet.get_usdc_balance()
                update_hot_wallet_balance(float(balance))
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    event="hedger.health.wallet_failed",
                    message="failed to fetch wallet balance",
                    error=str(exc),
                )
        if latest_commit_at:
            lag_seconds = (datetime.now(UTC) - latest_commit_at).total_seconds()
            record_event_lag(lag_seconds)
        status = "ok"
        if balance is None or not self.wallet:
            status = "degraded"
        redis_available = self._redis_available if self._redis_available is not None else self.redis is not None
        lock_mode = "redis" if redis_available else "memory"
        return {
            "status": status,
            "service": "hedger",
            "fx_stale": fx_stale,
            "latest_commit_at": latest_commit_at.isoformat() if latest_commit_at else None,
            "read_only": self.settings.admin_read_only,
            "wallet_unavailable": self.wallet is None,
            "hot_wallet_balance_usdc": str(balance) if balance is not None else None,
            "redis_available": redis_available,
            "lock_mode": lock_mode,
        }

    @staticmethod
    def _parse_category_limits(raw: str | None) -> dict[str, Decimal]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"HEDGER_RISK_CATEGORY_LIMITS invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("HEDGER_RISK_CATEGORY_LIMITS must be a JSON object")
        parsed: dict[str, Decimal] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            try:
                parsed[key.lower()] = Decimal(str(value))
            except (InvalidOperation, TypeError):
                logger.warning(
                    "Dropping invalid HEDGER_RISK_CATEGORY_LIMITS entry",
                    extra={"event": "hedger.config.invalid_category_limit", "key": key, "value": str(value)},
                )
                continue
        return parsed

    def _check_category_limits(
        self,
        market_id: str,
        category: str | None,
        snapshot: MarketExposureSnapshot,
    ) -> list[RiskBreach]:
        if not self._category_limits or not category:
            return []
        limit = self._category_limits.get(category.lower())
        if limit is None:
            return []
        absolute_usd = abs(snapshot.net_usd)
        if absolute_usd <= limit:
            return []
        return [
            RiskBreach(
                code="category_limit_exceeded",
                severity=RiskSeverity.WARN,
                message="Category exposure cap exceeded",
                market_id=market_id,
                detail={"category": category, "limit": str(limit), "absolute_usd": str(absolute_usd)},
            )
        ]

    def cached_health_snapshot(self) -> dict[str, Any] | None:
        ttl_seconds = max(int(self.settings.health_deep_cache_ttl_seconds or 0), 0)
        if ttl_seconds <= 0:
            return None
        snapshot = self._health_snapshot
        ts = self._health_snapshot_ts
        if snapshot is None or ts is None:
            return None
        age = (datetime.now(UTC) - ts).total_seconds()
        if age > ttl_seconds:
            return None
        return snapshot

    def store_health_snapshot(self, payload: dict[str, Any]) -> None:
        self._health_snapshot = payload
        self._health_snapshot_ts = datetime.now(UTC)

    async def _hydrate_from_storage(self) -> None:
        aggregates = await self.repository.load_commit_aggregates()
        hedge_totals = await self.repository.load_hedge_totals()
        if not aggregates:
            return
        for market_id, data in aggregates.items():
            hedged_usd = hedge_totals.get(market_id, Decimal("0"))
            await self.exposure_ledger.hydrate_market(
                market_id,
                yes_zen=data["yes_zen"],
                no_zen=data["no_zen"],
                yes_usd=data["yes_usd"],
                no_usd=data["no_usd"],
                hedged_usd=hedged_usd,
                last_update=data["last_update"] or datetime.now(UTC),
            )
        log_event(
            logger,
            logging.INFO,
            event="hedger.hydrate",
            message="restored exposure state from storage",
            markets=len(aggregates),
        )

    @staticmethod
    def _build_idempotency_key(commit: CommitEvent) -> str:
        if commit.idempotency_key:
            return commit.idempotency_key
        if commit.tx_hash:
            return f"tx:{commit.tx_hash}"
        return f"{commit.market_id}:{commit.account or 'unknown'}:{commit.committed_at.isoformat()}:{commit.stake_zen}"

    @staticmethod
    def _extract_filled_size(order_payload: dict, requested: Decimal) -> Decimal | None:
        """
        Extract the filled size from a polymarket order response, falling back to the requested size on missing data.
        """

        keys = ("filled_size", "size_filled", "filled")
        for key in keys:
            value = order_payload.get(key)
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    event="hedger.order.invalid_filled_size",
                    message="unable to parse filled size from order payload",
                    key=key,
                    value=value,
                    error=str(exc),
                )
                continue
        log_event(
            logger,
            logging.WARNING,
            event="hedger.order.unparseable_fill",
            message="no recognizable fill size key found in order payload; rejecting instead of assuming full fill",
            payload_keys=list(order_payload.keys()),
        )
        return None

    @staticmethod
    @asynccontextmanager
    async def _noop_async_lock() -> AsyncIterator[None]:
        yield

    async def _project_settlement(
        self, market_id: str, outcome_value: str, persist: bool = False
    ) -> dict[str, Any] | None:
        commits = await self.repository.get_commits_for_market(market_id)
        if not commits:
            return None

        winning_stake = sum([c.stake_zen for c in commits if c.direction == outcome_value], start=Decimal("0"))
        total_stake = sum([c.stake_zen for c in commits], start=Decimal("0"))
        hedge_totals = await self.repository.hedge_breakdown(market_id)
        borrow_usdc = hedge_totals.get("borrowed", Decimal("0"))
        unwind_usdc = hedge_totals.get("unwound", Decimal("0"))
        net_borrow_usdc = max(Decimal("0"), borrow_usdc - unwind_usdc)
        hedge_payloads = await self.repository.hedge_payloads(market_id)
        expected_payout = self._extract_expected_payout(hedge_payloads, net_borrow_usdc)
        stake_for_calc = winning_stake if winning_stake > 0 else total_stake
        if stake_for_calc <= 0:
            return None
        try:
            quote = await self.fx_oracle.get_quote()
        except (RetryError, httpx.HTTPError, InvalidOperation, ValueError):
            return None
        # Trading P&L from unwinds is already folded into net_borrow_usdc
        # (net_borrow = borrow - unwind, so sell-side gains reduce the net cost).
        # unrealized = 0 at settlement because all positions are being settled.
        # realized = 0 because the only remaining delta would be actual_claim - expected_payout,
        # which requires automated Polymarket claim tracking (not yet implemented).
        # TODO: once Polymarket claim automation lands, compute realized = actual_claim_usdc - expected_payout
        # TODO: implement periodic USDC/ZEN cross-chain (Polygon↔L3 ZEN) balance rebalancing
        realized = Decimal("0")
        unrealized = Decimal("0")
        expected_usdc_payout_if_win = expected_payout + max(unrealized, Decimal("0"))
        pricing = self.pricing_engine.quote_bet(stake_for_calc, quote.zen_usd)
        breakdown = self.bet_processor.settlement_breakdown(
            pricing,
            hedge_cost_usdc=net_borrow_usdc,
            expected_usdc_payout_if_win=expected_usdc_payout_if_win,
            user_won=winning_stake > 0,
            hedge_realized_pnl_usdc=realized,
        )
        treasury_snapshot = self.treasury.apply_settlement(breakdown)
        if persist:
            await self.repository.record_treasury_snapshot(
                market_id=market_id,
                outcome=outcome_value,
                stake_zen=breakdown.stake_zen,
                refund_zen=breakdown.refund_zen,
                rake_zen=breakdown.rake_zen,
                payout_profit_usdc=breakdown.payout_profit_usdc,
                borrowed_usdc=breakdown.borrowed_usdc,
                lp_share_usdc=breakdown.lp_share_usdc,
                repay_amount_usdc=breakdown.repay_amount_usdc,
                platform_usdc_revenue=breakdown.total_platform_usdc_revenue,
                zen_balance=treasury_snapshot.zen_balance,
                usdc_balance=treasury_snapshot.usdc_balance,
            )
        return {
            "pricing": pricing.model_dump(mode="json"),
            "breakdown": breakdown.model_dump(mode="json"),
            "treasury": treasury_snapshot.model_dump(mode="json"),
            "hedge_totals": {
                "borrowed_usdc": str(borrow_usdc),
                "unwound_usdc": str(unwind_usdc),
            },
        }

    @staticmethod
    def _extract_expected_payout(payloads: list[dict[str, Any]], fallback: Decimal) -> Decimal:
        for payload in payloads:
            value = payload.get("expected_usdc_payout") or payload.get("expected_payout_usdc")
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="hedger.payout.extract_failed",
                    message="failed to parse expected payout",
                    error=str(exc),
                )
        return fallback

    async def _build_prover_payload(self, market_id: str, outcome: str) -> dict[str, Any]:
        commits = await self.repository.get_commits_for_market(market_id)
        commit_payloads = [
            {
                "direction": row.direction,
                "stake_zen": str(row.stake_zen),
                "committed_at": row.committed_at.isoformat(),
                "tx_hash": row.tx_hash,
                "account": row.account,
            }
            for row in commits
        ]
        total_yes = sum([c.stake_zen for c in commits if c.direction == OutcomeSide.YES.value], start=Decimal("0"))
        total_no = sum([c.stake_zen for c in commits if c.direction == OutcomeSide.NO.value], start=Decimal("0"))
        return {
            "market_id": market_id,
            "outcome": outcome,
            "commit_count": len(commits),
            "total_yes_zen": f"{total_yes:.8f}",
            "total_no_zen": f"{total_no:.8f}",
            "commits": commit_payloads,
        }

    async def _build_and_persist_economics(self, market_id: str, outcome_value: str) -> dict[str, Any] | None:
        economics = await self._project_settlement(market_id, outcome_value, persist=True)
        return economics
