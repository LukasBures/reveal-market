from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from web3 import Web3

from .local_logging import log_event

logger = logging.getLogger("reveal_market.hedger.wallet")


ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
]


@dataclass(slots=True)
class WalletConfig:
    rpc_url: str
    chain_id: int
    private_key: str
    usdc_address: str
    usdc_decimals: int
    polymarket_exchange: str
    auto_approve: bool


class HedgerWallet:
    def __init__(self, config: WalletConfig) -> None:
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(config.rpc_url))
        self.account = self.w3.eth.account.from_key(config.private_key)
        self.address = self.account.address
        self.usdc = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.usdc_address),
            abi=ERC20_ABI,
        )

    def _to_units(self, amount: Decimal) -> int:
        return int((amount * Decimal(10**self.config.usdc_decimals)).to_integral_value())

    def _from_units(self, value: int) -> Decimal:
        return Decimal(value) / Decimal(10**self.config.usdc_decimals)

    def get_usdc_balance(self) -> Decimal:
        raw = self.usdc.functions.balanceOf(self.address).call()
        return self._from_units(int(raw))

    def get_allowance(self) -> int:
        return int(
            self.usdc.functions.allowance(
                self.address,
                Web3.to_checksum_address(self.config.polymarket_exchange),
            ).call()
        )

    def ensure_allowance(self) -> str | None:
        allowance = self.get_allowance()
        if allowance > 0 or not self.config.auto_approve:
            return None
        tx = self.usdc.functions.approve(
            Web3.to_checksum_address(self.config.polymarket_exchange),
            2**256 - 1,
        ).build_transaction(
            {
                "from": self.address,
                "nonce": self.w3.eth.get_transaction_count(self.address),
                "chainId": self.config.chain_id,
                "gas": 100000,
                "gasPrice": self.w3.eth.gas_price,
            }
        )
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        tx_hex = tx_hash.hex()
        log_event(
            logger,
            logging.INFO,
            event="hedger.wallet.approve",
            message="approval tx submitted; waiting for receipt",
            tx_hash=tx_hex,
        )
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        log_event(
            logger,
            logging.INFO,
            event="hedger.wallet.approve.confirmed",
            message="approval tx confirmed on-chain",
            tx_hash=tx_hex,
        )
        return tx_hex

    def has_sufficient_balance(self, required_usdc: Decimal) -> tuple[bool, Decimal]:
        balance = self.get_usdc_balance()
        return balance >= required_usdc, balance
