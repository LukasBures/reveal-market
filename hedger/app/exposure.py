from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal

from .fx import FxOracle
from .local_logging import log_event
from .metrics import update_exposure_metrics
from .risk import RiskEngine, RiskLimits
from .storage import HedgerRepository
from .types import CommitEvent, HedgeAction, HedgeInstruction, MarketExposureSnapshot, OutcomeSide, RiskBreach

logger = logging.getLogger("reveal_market.hedger.exposure")


class MarketExposure:
    def __init__(self, market_id: str):
        self.market_id = market_id
        self.yes_zen = Decimal("0")
        self.no_zen = Decimal("0")
        self.yes_usd = Decimal("0")
        self.no_usd = Decimal("0")
        self.hedged_usd = Decimal("0")
        self.last_update = datetime.now(UTC)

    def apply_commit(self, direction: OutcomeSide, stake_zen: Decimal, stake_usd: Decimal) -> None:
        if direction == OutcomeSide.YES:
            self.yes_zen += stake_zen
            self.yes_usd += stake_usd
        else:
            self.no_zen += stake_zen
            self.no_usd += stake_usd
        self.last_update = datetime.now(UTC)

    def register_fill(self, size_usd: Decimal, is_unwind: bool = False) -> None:
        if is_unwind:
            self.hedged_usd = max(Decimal("0"), self.hedged_usd - abs(size_usd))
        else:
            self.hedged_usd += abs(size_usd)
        self.last_update = datetime.now(UTC)

    @property
    def net_zen(self) -> Decimal:
        return self.yes_zen - self.no_zen

    @property
    def net_usd(self) -> Decimal:
        return self.yes_usd - self.no_usd

    @property
    def absolute_usd(self) -> Decimal:
        return abs(self.net_usd)

    @property
    def coverage_ratio(self) -> float:
        if self.absolute_usd == 0:
            return 1.0
        return float(min(1, self.hedged_usd / self.absolute_usd))

    def snapshot(self) -> MarketExposureSnapshot:
        return MarketExposureSnapshot(
            market_id=self.market_id,
            yes_zen=self.yes_zen,
            no_zen=self.no_zen,
            yes_usd=self.yes_usd,
            no_usd=self.no_usd,
            net_zen=self.net_zen,
            net_usd=self.net_usd,
            hedged_usd=self.hedged_usd,
            coverage_ratio=self.coverage_ratio,
            last_update=self.last_update,
        )


class ExposureLedger:
    """Serializes book updates, FX conversion, and risk evaluations."""

    def __init__(
        self,
        *,
        fx_oracle: FxOracle,
        limits: RiskLimits,
        risk_engine: RiskEngine,
        repository: HedgerRepository | None = None,
    ):
        self.fx_oracle = fx_oracle
        self.limits = limits
        self.risk_engine = risk_engine
        self.repository = repository
        self._markets: dict[str, MarketExposure] = {}
        self._lock = asyncio.Lock()
        self._lp_utilization = 0.0
        self._float_balance_zen = Decimal("0")

    async def hydrate_market(
        self,
        market_id: str,
        *,
        yes_zen: Decimal,
        no_zen: Decimal,
        yes_usd: Decimal,
        no_usd: Decimal,
        hedged_usd: Decimal,
        last_update: datetime,
    ) -> None:
        """Prime exposure state from persisted aggregates (used on restart)."""

        async with self._lock:
            market = MarketExposure(market_id)
            market.yes_zen = yes_zen
            market.no_zen = no_zen
            market.yes_usd = yes_usd
            market.no_usd = no_usd
            market.hedged_usd = hedged_usd
            market.last_update = last_update
            self._markets[market_id] = market
            update_exposure_metrics(market_id, float(yes_usd), float(no_usd), market.coverage_ratio)

    async def set_lp_utilization(self, utilization: float) -> None:
        async with self._lock:
            self._lp_utilization = utilization

    async def set_float_balance(self, balance_zen: Decimal) -> None:
        async with self._lock:
            self._float_balance_zen = balance_zen

    async def record_commit(
        self, commit: CommitEvent, *, idempotency_key: str | None = None
    ) -> tuple[MarketExposureSnapshot, HedgeInstruction | None, list[RiskBreach]]:
        quote = await self.fx_oracle.get_quote()
        stake_usd = self.fx_oracle.usd_from_zen(commit.stake_zen, quote)

        async with self._lock:
            market = self._markets.get(commit.market_id) or MarketExposure(commit.market_id)
            market.apply_commit(commit.direction, commit.stake_zen, stake_usd)
            self._markets[commit.market_id] = market
            total_absolute = self._total_absolute_usd()
            coverage_ratio = market.coverage_ratio
            breaches = self.risk_engine.check_limits(
                market_id=commit.market_id,
                market_net_usd=market.net_usd,
                absolute_market_usd=market.absolute_usd,
                total_absolute_usd=total_absolute,
                coverage_ratio=coverage_ratio,
                lp_utilization=self._lp_utilization,
                float_balance_zen=self._float_balance_zen,
            )
            instruction = self._plan_instruction(market)
            update_exposure_metrics(commit.market_id, float(market.yes_usd), float(market.no_usd), coverage_ratio)

        if self.repository:
            await self.repository.record_commit(commit, stake_usd, idempotency_key=idempotency_key)

        log_event(
            logger,
            logging.INFO,
            event="hedger.commit.recorded",
            message="commit recorded and exposure updated",
            market_id=commit.market_id,
            direction=commit.direction,
            stake_zen=str(commit.stake_zen),
            stake_usd=str(stake_usd),
        )
        return market.snapshot(), instruction, breaches

    def _total_absolute_usd(self) -> Decimal:
        return sum([market.absolute_usd for market in self._markets.values()], start=Decimal("0"))

    def _plan_instruction(self, market: MarketExposure) -> HedgeInstruction | None:
        if market.absolute_usd == 0:
            return None
        desired_coverage = Decimal(str(self.limits.coverage_ratio_target)) * market.absolute_usd
        delta = desired_coverage - market.hedged_usd
        if delta <= Decimal("0"):
            unwind_amount = abs(delta)
            action = HedgeAction.BUY if market.net_usd > 0 else HedgeAction.SELL
            return HedgeInstruction(
                market_id=market.market_id,
                hedge_outcome=OutcomeSide.YES if market.net_usd > 0 else OutcomeSide.NO,
                action=action,
                size_usd=unwind_amount,
                slippage_bps=30,
                reason="reduce_overhedge",
                target_coverage=float(self.limits.coverage_ratio_target),
                is_unwind=True,
            )
        action = HedgeAction.SELL if market.net_usd > 0 else HedgeAction.BUY
        size_usd = delta
        return HedgeInstruction(
            market_id=market.market_id,
            hedge_outcome=OutcomeSide.YES if market.net_usd > 0 else OutcomeSide.NO,
            action=action,
            size_usd=size_usd,
            slippage_bps=30,
            reason="exposure_change",
            target_coverage=float(self.limits.coverage_ratio_target),
        )

    async def register_fill(
        self, market_id: str, size_usd: Decimal, *, is_unwind: bool = False
    ) -> MarketExposureSnapshot | None:
        async with self._lock:
            market = self._markets.get(market_id)
            if not market:
                return None
            market.register_fill(size_usd, is_unwind=is_unwind)
            update_exposure_metrics(market_id, float(market.yes_usd), float(market.no_usd), market.coverage_ratio)
            return market.snapshot()

    async def snapshot(self) -> list[MarketExposureSnapshot]:
        async with self._lock:
            return [market.snapshot() for market in self._markets.values()]

    async def finalize_market(self, market_id: str) -> None:
        async with self._lock:
            self._markets.pop(market_id, None)
        update_exposure_metrics(market_id, 0.0, 0.0, 0.0)
