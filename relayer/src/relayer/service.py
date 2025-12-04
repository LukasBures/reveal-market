from dataclasses import dataclass
from typing import cast

from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress
from structlog import get_logger
from web3 import Web3
from web3.contract import Contract
from web3.types import TxParams, TxReceipt, Wei

from .abi import CLAIM_ABI, COMMIT_ABI

logger = get_logger()


@dataclass
class RelayerService:
    web3: Web3
    escrow: Contract
    account: LocalAccount
    chain_id: int

    def _build_base_tx(self, value: int = 0) -> TxParams:
        nonce = self.web3.eth.get_transaction_count(self.account.address)
        return TxParams(
            {
                "from": self.account.address,
                "nonce": nonce,
                "gasPrice": self.web3.eth.gas_price,
                "value": cast(Wei, value),
                "chainId": self.chain_id,
            }
        )

    def commit(self, payload: dict) -> dict:
        auth = (payload["commitment"], int(payload["nonce"]), int(payload["expiry"]))
        value = int(payload.get("ticket_value_wei") or 0)
        tx = self.escrow.functions.commitOnBehalf(
            payload["user"],
            payload["market"],
            auth,
            payload["signature"],
        ).build_transaction(self._build_base_tx(value))
        signed = self.account.sign_transaction(tx)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        receipt: TxReceipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        status = int(receipt["status"])
        logger.info("relayer.commit.sent", tx_hash=tx_hash.hex(), status=status)
        return {"txHash": tx_hash.hex(), "status": status}

    def claim(self, payload: dict) -> dict:
        market_addr: ChecksumAddress = self.web3.to_checksum_address(payload["market"])
        market = self.web3.eth.contract(address=market_addr, abi=CLAIM_ABI)
        tx = market.functions.claim(
            payload["user"],
            int(payload["ticket_id"]),
            int(payload["outcome_id"]),
            int(payload["amount"]),
            payload["salt"],
            payload["merkle_proof"],
        ).build_transaction(self._build_base_tx())
        signed = self.account.sign_transaction(tx)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        receipt: TxReceipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
        status = int(receipt["status"])
        logger.info("relayer.claim.sent", tx_hash=tx_hash.hex(), status=status)
        return {"txHash": tx_hash.hex(), "status": status}


def build_service(web3: Web3, escrow_address: str, account: LocalAccount, chain_id: int) -> RelayerService:
    escrow_addr: ChecksumAddress = web3.to_checksum_address(escrow_address)
    escrow = web3.eth.contract(address=escrow_addr, abi=COMMIT_ABI)
    return RelayerService(web3=web3, escrow=escrow, account=account, chain_id=chain_id)
