from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from web3 import HTTPProvider, Web3
from web3.contract.contract import Contract
from web3.middleware import geth_poa_middleware

from .local_logging import log_event

logger = logging.getLogger("reveal_market.hedger.vault")


@dataclass
class VaultTxConfig:
    rpc_url: str
    chain_id: int
    private_key: str
    sender: str
    gas_price_gwei: int | None = None


class BaseLpVaultClient:
    """Non-production helper used only for testing; production uses OnChainLpVaultClient."""

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
            message="borrowed USDC for hedge (stub)",
            amount_usd=str(amount_usd),
            destination=destination,
            utilization=self.utilization,
        )
        return {"amount": str(amount_usd), "destination": destination or "hedger_wallet", "mode": "stub"}

    async def repay_from_hedge(self, amount_usd: Decimal, source: str | None = None) -> dict:
        self.utilization = max(0.0, self.utilization - float(amount_usd) / 1_000_000)
        log_event(
            logger,
            logging.INFO,
            event="vault.repay",
            message="repaid USDC to LP vault (stub)",
            amount_usd=str(amount_usd),
            source=source,
            utilization=self.utilization,
        )
        return {"amount": str(amount_usd), "source": source or "hedger_wallet", "mode": "stub"}

    async def current_utilization(self) -> float:
        return self.utilization

    async def get_pnl(self) -> tuple[float, float]:
        return self.realized_pnl, self.unrealized_pnl


class OnChainLpVaultClient(BaseLpVaultClient):
    """Web3-backed LP vault client that signs and sends transactions."""

    ABI = [
        {
            "inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"}, {"internalType": "address", "name": "to", "type": "address"}],
            "name": "borrow",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [],
            "name": "utilization",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [{"internalType": "uint256", "name": "amount", "type": "uint256"}],
            "name": "repay",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
    ]

    def __init__(self, vault_address: str, tx_config: VaultTxConfig):
        super().__init__(vault_address)
        self.tx_config = tx_config
        self.w3 = Web3(HTTPProvider(tx_config.rpc_url))
        # Support PoA chains if needed.
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        self.account = self.w3.eth.account.from_key(tx_config.private_key)
        self.contract: Contract = self.w3.eth.contract(address=Web3.to_checksum_address(vault_address), abi=self.ABI)

    def _to_usdc_units(self, amount_usd: Decimal) -> int:
        return int((amount_usd * Decimal(1_000_000)).to_integral_value())

    async def borrow_for_hedge(self, amount_usd: Decimal, destination: str | None = None) -> dict:
        destination = destination or self.account.address
        tx = self.contract.functions.borrow(
            self._to_usdc_units(amount_usd), Web3.to_checksum_address(destination)
        ).build_transaction(self._tx_args())
        receipt = await self._send_tx(tx)
        util = await self.current_utilization()
        return {"tx_hash": receipt["transactionHash"].hex(), "utilization": util, "mode": "onchain"}

    async def repay_from_hedge(self, amount_usd: Decimal, source: str | None = None) -> dict:
        tx = self.contract.functions.repay(self._to_usdc_units(amount_usd)).build_transaction(self._tx_args())
        receipt = await self._send_tx(tx)
        util = await self.current_utilization()
        return {"tx_hash": receipt["transactionHash"].hex(), "utilization": util, "mode": "onchain"}

    async def current_utilization(self) -> float:
        util_bps = self.contract.functions.utilization().call()
        return float(util_bps) / 10_000

    async def get_pnl(self) -> tuple[float, float]:
        # On-chain vault doesn't track PnL; return zeros to avoid misleading metrics.
        return 0.0, 0.0

    def _tx_args(self) -> dict[str, Any]:
        gas_price = None
        if self.tx_config.gas_price_gwei is not None:
            gas_price = self.w3.to_wei(self.tx_config.gas_price_gwei, "gwei")
        return {
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "chainId": self.tx_config.chain_id,
            "gasPrice": gas_price,
        }

    async def _send_tx(self, tx: dict) -> dict:
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        log_event(
            logger,
            logging.INFO,
            event="vault.tx.sent",
            message="vault transaction sent",
            tx_hash=tx_hash.hex(),
            status=receipt.status,
        )
        return receipt
