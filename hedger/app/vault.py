from __future__ import annotations

import logging
from decimal import Decimal

from .logging_config import log_event

logger = logging.getLogger("reveal_market.hedger.vault")


class BaseLpVaultClient:
    """Stub client for the Base LP vault hedging hooks."""

    def __init__(self, vault_address: str):
        self.vault_address = vault_address
        self.utilization = 0.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0

    async def borrow_for_hedge(self, amount_usd: Decimal, destination: str | None = None) -> dict:
        self.utilization = min(1.0, self.utilization + float(amount_usd) / 1_000_000)
        log_event(
            logger,
            logging.INFO,
            event="vault.borrow",
            message="borrowed USDC for hedge",
            amount_usd=str(amount_usd),
            destination=destination,
            utilization=self.utilization,
        )
        return {"amount": str(amount_usd), "destination": destination or "hedger_wallet"}

    async def repay_from_hedge(self, amount_usd: Decimal, source: str | None = None) -> dict:
        self.utilization = max(0.0, self.utilization - float(amount_usd) / 1_000_000)
        log_event(
            logger,
            logging.INFO,
            event="vault.repay",
            message="repaid USDC to LP vault",
            amount_usd=str(amount_usd),
            source=source,
            utilization=self.utilization,
        )
        return {"amount": str(amount_usd), "source": source or "hedger_wallet"}

    async def current_utilization(self) -> float:
        return self.utilization

    async def get_pnl(self) -> tuple[float, float]:
        return self.realized_pnl, self.unrealized_pnl
