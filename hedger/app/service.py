from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

from redis.asyncio import Redis

from .config import Settings
from .exposure import ExposureLedger
from .fx import FxOracle
from .local_logging import log_event
from .locks import RedisLockManager
from .metrics import (
    HEDGE_EXECUTIONS,
    record_event_lag,
    record_pnl,
    update_float_and_utilization,
)
from .polymarket import PolymarketClient
from .risk import RiskEngine, RiskLimits
from .settlement import SettlementCoordinator
from .storage import HedgerRepository
from .types import CommitEvent, HedgeInstruction, MarketExposureSnapshot, OutcomeSide
from .vault import BaseLpVaultClient

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
            haircut_bps=settings.fx_haircut_bps,
            timeout_seconds=settings.fx_timeout_seconds,
            max_age_seconds=settings.fx_max_age_seconds,
            fallback_zen_usd=settings.fx_fallback_price,
        )
        self.polymarket_client = PolymarketClient(
            base_url=settings.polymarket_api_base,
            timeout_seconds=settings.polymarket_timeout_seconds,
            retry_attempts=settings.polymarket_retry_attempts,
            retry_backoff_seconds=settings.polymarket_retry_backoff_seconds,
        )
        self.vault_client = BaseLpVaultClient(settings.lp_vault_address)
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

        lock_ctx = self.lock_manager.lock(f"commit:{commit.market_id}") if self.lock_manager else asyncio.nullcontext()
        async with lock_ctx:
            snapshot, instruction, breaches = await self.exposure_ledger.record_commit(
                commit, idempotency_key=idemp_key
            )
        response: dict = {
            "snapshot": snapshot,
            "hedge_instruction": instruction,
            "breaches": breaches,
        }
        if instruction:
            hedge_result = await self._execute_hedge(instruction)
            response["hedge_execution"] = hedge_result
        if commit.stream_offset:
            self.repository.set_replay_offset(self.settings.commit_stream_name, commit.stream_offset)
        return response

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

            if instruction.is_unwind:
                repay = await self.vault_client.repay_from_hedge(instruction.size_usd)
                borrow_receipt = {"repay": repay}
            else:
                borrow_receipt = await self.vault_client.borrow_for_hedge(instruction.size_usd)

            await self.exposure_ledger.register_fill(
                instruction.market_id, instruction.size_usd, is_unwind=instruction.is_unwind
            )
            await self.repository.record_hedge_instruction(instruction, response_payload=quote)
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
                size_usd=str(instruction.size_usd),
                utilization=utilization,
            )
            return {
                "borrow": borrow_receipt,
                "quote": quote,
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
        return {"status": "resolved", "payload": payload, "proof": response}

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
    @asynccontextmanager
    async def _noop_async_lock():
        yield

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
