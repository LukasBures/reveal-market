from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from .local_logging import log_event
from .types import HedgeAction

logger = logging.getLogger("reveal_market.hedger.clob")


@dataclass(slots=True)
class ClobConfig:
    host: str
    chain_id: int
    private_key: str
    api_key: str
    api_secret: str
    api_passphrase: str
    funder: str
    signature_type: int = 0  # 0 = EOA


class HedgerClob:
    def __init__(self, config: ClobConfig) -> None:
        self.config = config
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("py-clob-client is required for CLOB trading") from exc

        self.client = ClobClient(
            config.host,
            key=config.private_key,
            chain_id=config.chain_id,
            signature_type=config.signature_type,
            funder=config.funder,
        )
        creds = ApiCreds(
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.api_passphrase,
        )
        self.client.set_api_creds(creds)

    def place_market_order(
        self,
        token_id: str,
        amount_usd: Decimal,
        action: HedgeAction,
    ) -> dict:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        side = BUY if action == HedgeAction.BUY else SELL
        order_args = MarketOrderArgs(
            token_id=str(token_id),
            amount=float(amount_usd),
            side=side,
            order_type=OrderType.FAK,
        )
        signed = self.client.create_market_order(order_args)
        response = self.client.post_order(signed, OrderType.FAK)
        log_event(
            logger,
            logging.INFO,
            event="hedger.clob.order",
            message="submitted clob market order",
            token_id=str(token_id),
            side=str(side),
            amount_usd=str(amount_usd),
        )
        return response
