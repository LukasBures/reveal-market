from __future__ import annotations

import logging
from decimal import Decimal

from .local_logging import log_event
from .vault import BaseLpVaultClient

logger = logging.getLogger("reveal_market.hedger.usdc")


class HedgerUSDC:
    """Single-responsibility helper for LP vault borrowing/repayment."""

    def __init__(self, vault_client: BaseLpVaultClient, *, max_utilization: float = 0.98):
        self.vault_client = vault_client
        self.max_utilization = max_utilization

    async def can_hedge(self, required_usdc: Decimal) -> tuple[bool, float]:
        """Return whether enough LP liquidity exists for a hedge."""

        utilization = await self.vault_client.current_utilization()
        if utilization >= 1:
            return False, utilization
        projected = utilization + float(required_usdc) / 1_000_000
        return projected <= self.max_utilization, projected

    async def borrow(self, amount_usdc: Decimal) -> dict:
        ok, projected = await self.can_hedge(amount_usdc)
        if not ok:
            log_event(
                logger,
                logging.WARNING,
                event="hedger.lp.unavailable",
                message="LP vault has insufficient capacity for new hedge",
                requested=str(amount_usdc),
                projected_utilization=projected,
            )
            return {"status": "rejected", "reason": "lp_unavailable", "projected_utilization": projected}
        receipt = await self.vault_client.borrow_for_hedge(amount_usdc)
        utilization = await self.vault_client.current_utilization()
        return {"status": "borrowed", "receipt": receipt, "utilization": utilization}

    async def repay(self, amount_usdc: Decimal) -> dict:
        receipt = await self.vault_client.repay_from_hedge(amount_usdc)
        utilization = await self.vault_client.current_utilization()
        return {"status": "repaid", "receipt": receipt, "utilization": utilization}
