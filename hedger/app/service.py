from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from redis.asyncio import Redis

from .bet_processor_zen import BetProcessorZen
from .bridge import BridgeClient
from .config import Settings
from .exposure import ExposureLedger
from .fx import FxOracle
from .hedger_usdc import HedgerUSDC
from .local_logging import log_event
from .locks import RedisLockManager
from .metrics import (
    HEDGE_EXECUTIONS,
    record_event_lag,
    record_pnl,
    update_float_and_utilization,
)
from .polymarket import PolymarketClient
from .pricing_engine import PricingEngine
from .risk import RiskEngine, RiskLimits
from .settlement import SettlementCoordinator
from .storage import HedgerRepository
from .treasury_manager import TreasuryManager
from .types import CommitEvent, HedgeInstruction, MarketExposureSnapshot, OutcomeSide
from .vault import OnChainLpVaultClient, VaultTxConfig

logger = logging.getLogger("reveal_market.hedger.service")


class HedgerService:
    """Coordinates exposure ingestion, hedging, settlements, and float controls."""

    def __init__(self, settings: Settings):
        limits = RiskLimits(
            max_global_exposure_usd=settings.risk_max_global_exposure_usd,
            max_per_market_usd=settings.risk_max_per_market_usd,
            coverage_ratio_target=settings.risk_coverage_ratio_target,
            lp_utilization_limit=settings.risk_lp_utilization_limit,
            float_min_zen=settings.float_min_zen,
        )
        self.settings = settings
        self.repository = HedgerRepository(settings.database_url)
        self.risk_engine = RiskEngine(limits)
        self.redis: Redis | None = None
        self.fx_oracle = FxOracle(
            feed_url=settings.fx_feed_url,
            feed_alt_url=settings.fx_feed_alt_url,
            haircut_bps=settings.fx_haircut_bps,
            timeout_seconds=settings.fx_timeout_seconds,
            max_age_seconds=settings.fx_max_age_seconds,
            fallback_zen_usd=settings.fx_fallback_price,
        )
        self.pricing_engine = PricingEngine(
            haircut_percent=settings.haircut_percent,
            worsen_percent=settings.worsen_percent,
            rake_percent=settings.rake_percent,
        )
        self.treasury = TreasuryManager(lp_share_percent=settings.lp_share_percent)
        self.bet_processor = BetProcessorZen(self.pricing_engine, self.treasury)
        self.polymarket_client = PolymarketClient(
            base_url=settings.polymarket_api_base,
            timeout_seconds=settings.polymarket_timeout_seconds,
            retry_attempts=settings.polymarket_retry_attempts,
            retry_backoff_seconds=settings.polymarket_retry_backoff_seconds,
        )
        self.bridge_client = BridgeClient(
            base_url=settings.bridge_endpoint,
            timeout_seconds=settings.polymarket_timeout_seconds,
            retry_attempts=settings.polymarket_retry_attempts,
            retry_backoff_seconds=settings.polymarket_retry_backoff_seconds,
        )
        if not (settings.vault_rpc_url and settings.vault_private_key and settings.vault_sender_address):
            raise ValueError("Vault RPC/key/sender are required for vault client")
        tx_cfg = VaultTxConfig(
            rpc_url=settings.vault_rpc_url,
            chain_id=settings.vault_chain_id,
            private_key=settings.vault_private_key,
            sender=settings.vault_sender_address,
            gas_price_gwei=settings.vault_gas_price_gwei,
        )
        self.vault_client = OnChainLpVaultClient(settings.lp_vault_address, tx_cfg)
        self.hedger_usdc = HedgerUSDC(self.vault_client, max_utilization=limits.lp_utilization_limit)
        self.exposure_ledger = ExposureLedger(
            fx_oracle=self.fx_oracle,
            limits=limits,
            risk_engine=self.risk_engine,
            repository=self.repository,
        )
        self.settlement = SettlementCoordinator(
            base_url=settings.prover_base_url,
            timeout_seconds=settings.prover_timeout_seconds,
            repository=self.repository,
        )
        self.lock_manager: RedisLockManager | None = None
        self._noop_lock = self._noop_async_lock()

    async def startup(self) -> None:
        if self.settings.run_migrations_on_startup:
            self.repository.create_schema()
        self.redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        self.lock_manager = RedisLockManager(
            self.redis, self.settings.redis_lock_ttl_seconds, self.settings.redis_idempotency_ttl_seconds
        )
        await self.fx_oracle.refresh()
        await self._hydrate_from_storage()
        log_event(
            logger,
            logging.INFO,
            event="hedger.startup",
            message="hedger service initialised",
            polymarket_api=self.settings.polymarket_api_base,
            redis_url=self.settings.redis_url,
        )

    async def ingest_commit(self, commit: CommitEvent) -> dict:
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
        if self.repository.commit_exists(idemp_key):
            log_event(
                logger,
                logging.INFO,
                event="hedger.commit.duplicate.db",
                message="commit dropped (duplicate idempotency key in DB)",
                market_id=commit.market_id,
                idempotency_key=idemp_key,
            )
            return {"status": "duplicate", "idempotency_key": idemp_key}

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
        except Exception as exc:
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

        lp_ok, projected_util = await self.hedger_usdc.can_hedge(pricing.hedge_usdc)
        if not lp_ok:
            return {
                "status": "rejected",
                "reason": "lp_unavailable",
                "projected_utilization": projected_util,
                "pricing": pricing.model_dump(mode="json"),
            }

        lock_ctx = self.lock_manager.lock(f"commit:{commit.market_id}") if self.lock_manager else asyncio.nullcontext()
        async with lock_ctx:
            snapshot, instruction, breaches = await self.exposure_ledger.record_commit(
                commit, idempotency_key=idemp_key, stake_usd=pricing.hedge_usdc
            )
        response: dict = {
            "snapshot": snapshot,
            "hedge_instruction": instruction,
            "breaches": breaches,
            "pricing": pricing.model_dump(mode="json"),
        }
        if instruction:
            hedge_result = await self._execute_hedge(instruction)
            response["hedge_execution"] = hedge_result
        if commit.stream_offset:
            self.repository.set_replay_offset(self.settings.commit_stream_name, commit.stream_offset)
        return response

    async def _validate_signed_quote(self, commit, quote_payload) -> tuple[bool, str | None]:
        """
        If a SignedQuote payload is attached to the commit, ensure it is fresh and matches stake/outcome/fx.
        This mirrors the on-chain digest and prevents hedging against tampered client inputs.
        """

        market_address = getattr(commit, "market_address", None)
        outcome_id = getattr(commit, "outcome_id", None)
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct
            from web3 import Web3
        except Exception as exc:  # pragma: no cover - runtime dependency guard
            log_event(
                logger,
                logging.WARNING,
                event="hedger.commit.quote_validation_unavailable",
                message="signature validation skipped (missing web3/eth_account)",
                error=str(exc),
            )
            return True, None

        try:
            stake_wei = int(quote_payload.get("stake_wei"))
            fx_scaled = int(quote_payload.get("zen_usd_scaled"))
            expiry_ts = int(quote_payload.get("expiry_ts"))
            chain_id = int(quote_payload.get("chain_id"))
        except Exception as exc:
            logger.debug("quote parse failed", extra={"event": "hedger.commit.quote_parse_failed", "error": str(exc)})
            return False, "quote_fields_invalid"

        # Reject expired quotes before hedging.
        now = datetime.now(UTC).timestamp()
        if expiry_ts <= now:
            return False, "quote_expired"

        # Basic field alignment with the commit.
        if int(commit.stake_zen * Decimal("1e18")) != stake_wei:
            return False, "quote_stake_mismatch"
        if (
            market_address
            and quote_payload.get("market_address")
            and market_address.lower() != quote_payload.get("market_address").lower()
        ):
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
        except Exception as exc:
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
        except Exception as exc:
            logger.debug(
                "quote FX validation skipped",
                extra={"event": "hedger.commit.quote_fx_invalid", "error": str(exc)},
            )

        return True, None

    async def _execute_hedge(self, instruction: HedgeInstruction) -> dict:
        lock_ctx = self.lock_manager.lock(f"hedge:{instruction.market_id}") if self.lock_manager else self._noop_lock
        async with lock_ctx:
            quote = await self.polymarket_client.quote_execution(
                instruction.market_id,
                outcome=instruction.hedge_outcome,
                action=instruction.action,
                size_usd=instruction.size_usd,
            )
            if not self._quote_within_slippage(quote):
                log_event(
                    logger,
                    logging.WARNING,
                    event="hedger.hedge.rejected",
                    message="hedge aborted due to slippage limit",
                    market_id=instruction.market_id,
                    slippage_bps=quote.get("slippage_bps"),
                    max_slippage_bps=self.settings.max_slippage_bps,
                )
                return {"status": "rejected", "reason": "slippage_limit", "quote": quote}

            order_payload: dict = {}
            filled_size = instruction.size_usd
            client_order_id = f"{instruction.market_id}:{int(instruction.created_at.timestamp() * 1000)}"
            if hasattr(self.polymarket_client, "execute_order"):
                try:
                    order_payload = await self.polymarket_client.execute_order(  # type: ignore[attr-defined]
                        instruction.market_id,
                        outcome=instruction.hedge_outcome,
                        action=instruction.action,
                        size_usd=instruction.size_usd,
                        max_slippage_bps=self.settings.max_slippage_bps,
                        client_order_id=client_order_id,
                    )
                    filled_size = self._extract_filled_size(order_payload, instruction.size_usd)
                except Exception as exc:  # pragma: no cover - network errors handled via retry
                    log_event(
                        logger,
                        logging.ERROR,
                        event="hedger.hedge.order_failed",
                        message="polymarket order failed",
                        market_id=instruction.market_id,
                        error=str(exc),
                    )
                    return {"status": "rejected", "reason": "order_failed", "error": str(exc)}

            if filled_size <= 0:
                return {
                    "status": "rejected",
                    "reason": "no_fill",
                    "order": order_payload,
                    "quote": quote,
                }

            if instruction.is_unwind:
                borrow_receipt = await self.hedger_usdc.repay(filled_size)
            else:
                borrow_receipt = await self.hedger_usdc.borrow(filled_size)
                if borrow_receipt.get("status") == "rejected":
                    return borrow_receipt

            await self.exposure_ledger.register_fill(
                instruction.market_id, filled_size, is_unwind=instruction.is_unwind
            )
            await self.repository.record_hedge_instruction(instruction, response_payload=quote)
            utilization = borrow_receipt.get("utilization") if isinstance(borrow_receipt, dict) else None
            if utilization is None:
                utilization = await self.vault_client.current_utilization()
            update_float_and_utilization(float_zen=None, lp_utilization=utilization)
            realized, unrealized = await self.vault_client.get_pnl()
            record_pnl(realized_usd=realized, unrealized_usd=unrealized)
            HEDGE_EXECUTIONS.labels(action=instruction.action, outcome=instruction.hedge_outcome).inc()
            log_event(
                logger,
                logging.INFO,
                event="hedger.hedge.executed",
                message="hedge placed on Polymarket",
                market_id=instruction.market_id,
                action=instruction.action,
                size_usd=str(filled_size),
                utilization=utilization,
                partial_fill=float(filled_size / instruction.size_usd) if instruction.size_usd else 1.0,
            )
            return {
                "borrow": borrow_receipt,
                "quote": quote,
                "order": order_payload,
                "filled_size_usd": str(filled_size),
                "utilization": utilization,
            }

    async def exposures(self) -> list[MarketExposureSnapshot]:
        return await self.exposure_ledger.snapshot()

    async def reconcile_lp_utilization(self) -> float:
        utilization = await self.vault_client.current_utilization()
        await self.exposure_ledger.set_lp_utilization(utilization)
        update_float_and_utilization(float_zen=None, lp_utilization=utilization)
        return utilization

    async def trigger_settlement(self, market_id: str, payload: dict) -> dict:
        return await self.settlement.request_settlement(market_id, payload)

    async def settle_market(self, market_id: str, outcome: OutcomeSide | str) -> dict:
        if isinstance(outcome, OutcomeSide):
            outcome_value = outcome.value
        else:
            outcome_value = outcome
        lock_ctx = self.lock_manager.lock(f"settle:{market_id}") if self.lock_manager else self._noop_lock
        async with lock_ctx:
            if self.repository.is_market_resolved(market_id):
                return {"status": "already_resolved", "market_id": market_id}

            payload = self._build_prover_payload(market_id, outcome_value)
            log_event(
                logger,
                logging.INFO,
                event="hedger.settlement.request",
                message="requesting settlement proof",
                market_id=market_id,
                outcome=outcome_value,
                commit_count=len(payload["commits"]),
            )
            response = await self.settlement.request_settlement(market_id, payload)
            await self.repository.record_settlement(
                market_id=market_id,
                outcome=outcome_value,
                proof_payload=response,
                prover_latency_seconds=None,
                submitted_tx=None,
            )
            economics = await self._build_and_persist_economics(market_id, outcome_value)
            self.repository.mark_market_resolved(market_id, outcome_value)
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
    ) -> dict:
        """
        Manually request a bridge transfer. Direction must be `usdc_to_zen` or `zen_to_usdc`.
        """

        slippage = slippage_bps if slippage_bps is not None else self.settings.max_slippage_bps
        idempotency = f"{direction}:{destination}:{amount}"
        if direction == "usdc_to_zen":
            return await self.bridge_client.bridge_to_zen(
                amount, destination, slippage_bps=slippage, idempotency=idempotency
            )
        if direction == "zen_to_usdc":
            return await self.bridge_client.bridge_to_usdc(
                amount, destination, slippage_bps=slippage, idempotency=idempotency
            )
        raise ValueError("direction must be 'usdc_to_zen' or 'zen_to_usdc'")

    async def health(self) -> dict:
        latest_commit_at = self.repository.latest_commit_timestamp()
        fx_stale = self.fx_oracle.stale()
        utilization = await self.vault_client.current_utilization()
        if latest_commit_at:
            lag_seconds = (datetime.now(UTC) - latest_commit_at).total_seconds()
            record_event_lag(lag_seconds)
        return {
            "fx_stale": fx_stale,
            "latest_commit_at": latest_commit_at.isoformat() if latest_commit_at else None,
            "lp_utilization": utilization,
        }

    async def _hydrate_from_storage(self) -> None:
        aggregates = self.repository.load_commit_aggregates()
        hedge_totals = self.repository.load_hedge_totals()
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

    def _build_idempotency_key(self, commit: CommitEvent) -> str:
        if commit.idempotency_key:
            return commit.idempotency_key
        if commit.tx_hash:
            return f"tx:{commit.tx_hash}"
        return f"{commit.market_id}:{commit.account or 'unknown'}:{commit.committed_at.isoformat()}:{commit.stake_zen}"

    def _quote_within_slippage(self, quote: dict) -> bool:
        slippage = quote.get("slippage_bps") or quote.get("priceImpactBps") or 0
        try:
            return int(slippage) <= self.settings.max_slippage_bps
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _extract_filled_size(order_payload: dict, requested: Decimal) -> Decimal:
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
        return requested

    @staticmethod
    @asynccontextmanager
    async def _noop_async_lock():
        yield

    async def _project_settlement(self, market_id: str, outcome_value: str, persist: bool = False) -> dict | None:
        commits = self.repository.get_commits_for_market(market_id)
        if not commits:
            return None

        winning_stake = sum([c.stake_zen for c in commits if c.direction == outcome_value], start=Decimal("0"))
        total_stake = sum([c.stake_zen for c in commits], start=Decimal("0"))
        hedge_totals = self.repository.hedge_breakdown(market_id)
        borrow_usdc = hedge_totals.get("borrowed", Decimal("0"))
        unwind_usdc = hedge_totals.get("unwound", Decimal("0"))
        net_borrow_usdc = max(Decimal("0"), borrow_usdc - unwind_usdc)
        hedge_payloads = self.repository.hedge_payloads(market_id)
        expected_payout = self._extract_expected_payout(hedge_payloads, net_borrow_usdc)
        stake_for_calc = winning_stake if winning_stake > 0 else total_stake
        if stake_for_calc <= 0:
            return None
        try:
            quote = await self.fx_oracle.get_quote()
        except Exception:
            return None
        realized, unrealized = await self.vault_client.get_pnl()
        expected_usdc_payout_if_win = expected_payout + Decimal(str(max(unrealized, 0.0)))
        pricing = self.pricing_engine.quote_bet(stake_for_calc, quote.zen_usd)
        breakdown = self.bet_processor.settlement_breakdown(
            pricing,
            hedge_cost_usdc=net_borrow_usdc,
            expected_usdc_payout_if_win=expected_usdc_payout_if_win,
            user_won=winning_stake > 0,
            hedge_realized_pnl_usdc=Decimal(str(realized)),
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
    def _extract_expected_payout(payloads: list[dict], fallback: Decimal) -> Decimal:
        for payload in payloads:
            value = payload.get("expected_usdc_payout") or payload.get("expected_payout_usdc")
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except Exception as exc:
                log_event(
                    logger,
                    logging.DEBUG,
                    event="hedger.payout.extract_failed",
                    message="failed to parse expected payout",
                    error=str(exc),
                )
        return fallback

    def _build_prover_payload(self, market_id: str, outcome: str) -> dict:
        commits = self.repository.get_commits_for_market(market_id)
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

    async def _build_and_persist_economics(self, market_id: str, outcome_value: str) -> dict | None:
        economics = await self._project_settlement(market_id, outcome_value, persist=True)
        return economics
