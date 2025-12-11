import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress
from structlog import get_logger
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import TimeExhausted, Web3Exception
from web3.types import BlockData, TxParams, TxReceipt, Wei

from .abi import CLAIM_ABI, COMMIT_ABI
from .metrics import HEALTH_CHECKS, TX_LATENCY, TX_OUTCOMES

logger = get_logger()

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
]


class TxSendError(RuntimeError):
    def __init__(self, message: str, *, nonce: int | None = None):
        super().__init__(message)
        self.nonce = nonce


@dataclass
class RelayerService:
    web3: Web3
    escrow: Contract
    account: LocalAccount
    chain_id: int
    rpc_url: str
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5
    tx_timeout_seconds: int = 120
    max_block_age_seconds: int = 60
    min_relayer_balance_wei: int = 0
    min_escrow_token_balance_wei: int = 0
    min_relayer_token_allowance_wei: int = 0
    fee_bump_percent: float = 0.15

    def _build_base_tx(self, value: int = 0, nonce_override: int | None = None, bump_factor: float = 1.0) -> TxParams:
        nonce = nonce_override
        if nonce is None:
            nonce = self.web3.eth.get_transaction_count(self.account.address, "pending")
        base: dict[str, int | str | Wei] = {
            "from": self.account.address,
            "nonce": nonce,
            "value": cast(Wei, value),
            "chainId": self.chain_id,
        }
        fee_params = self._build_fee_params(bump_factor)
        return cast(TxParams, {**base, **fee_params})

    def _build_fee_params(self, bump_factor: float = 1.0) -> dict[str, int]:
        try:
            latest_block: BlockData = self.web3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas")
            if base_fee is not None:
                priority_fee = int(self.web3.eth.max_priority_fee * bump_factor)
                max_fee = int(base_fee * 2 * bump_factor + priority_fee)
                return {"maxPriorityFeePerGas": priority_fee, "maxFeePerGas": max_fee}
        except (Web3Exception, ValueError, TypeError) as err:
            logger.warning("relayer.fee_params.fallback", error=str(err))
        # legacy fallback
        gas_price = int(self.web3.eth.gas_price * bump_factor)
        return {"gasPrice": gas_price}

    def _send_and_wait(self, tx: TxParams, action: str) -> dict[str, str | int]:
        last_err: Exception | None = None
        start = time.perf_counter()
        nonce_value = tx.get("nonce")
        if nonce_value is None:
            raise TxSendError("nonce missing from transaction")
        nonce_used = cast(int, nonce_value)
        for attempt in range(1, self.max_retries + 1):
            try:
                signed = self.account.sign_transaction(tx)
                tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
                receipt: TxReceipt = self.web3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self.tx_timeout_seconds
                )
                status = int(receipt["status"])
                logger.info(f"relayer.{action}.sent", tx_hash=tx_hash.hex(), status=status, attempt=attempt)
                TX_OUTCOMES.labels(action=action, outcome="success").inc()
                TX_LATENCY.labels(action=action).observe(time.perf_counter() - start)
                return {"txHash": tx_hash.hex(), "status": status, "nonce": nonce_used}
            except TimeExhausted as err:
                last_err = err
                logger.warning(
                    f"relayer.{action}.timeout",
                    attempt=attempt,
                    timeout=self.tx_timeout_seconds,
                    error=str(err),
                )
                TX_OUTCOMES.labels(action=action, outcome="timeout").inc()
            except (Web3Exception, ValueError) as err:
                last_err = err
                logger.warning(f"relayer.{action}.error", attempt=attempt, error=str(err))
                TX_OUTCOMES.labels(action=action, outcome="error").inc()

            time.sleep(self.retry_backoff_seconds * attempt)

        logger.error(f"relayer.{action}.failed", error=str(last_err))
        TX_OUTCOMES.labels(action=action, outcome="failed").inc()
        raise TxSendError(str(last_err) if last_err else f"{action} failed without error", nonce=nonce_used)

    def commit(
        self, payload: Mapping[str, Any], *, nonce_override: int | None = None, bump_factor: float = 1.0
    ) -> dict[str, str | int]:
        auth = (payload["commitment"], int(payload["nonce"]), int(payload["expiry"]))
        value = int(payload.get("ticket_value_wei") or 0)
        tx = self.escrow.functions.commitOnBehalf(
            payload["user"],
            payload["market"],
            auth,
            payload["signature"],
        ).build_transaction(self._build_base_tx(value, nonce_override, bump_factor))
        return self._send_and_wait(tx, "commit")

    def claim(
        self, payload: Mapping[str, Any], *, nonce_override: int | None = None, bump_factor: float = 1.0
    ) -> dict[str, str | int]:
        market_addr: ChecksumAddress = self.web3.to_checksum_address(payload["market"])
        market = self.web3.eth.contract(address=market_addr, abi=CLAIM_ABI)
        tx = market.functions.claim(
            payload["user"],
            int(payload["ticket_id"]),
            int(payload["outcome_id"]),
            int(payload["amount"]),
            payload["salt"],
            payload["merkle_proof"],
        ).build_transaction(self._build_base_tx(0, nonce_override, bump_factor))
        return self._send_and_wait(tx, "claim")

    def health(self) -> dict[str, Any]:
        issues: list[str] = []
        connected = self.web3.is_connected()

        block_number: int | None = None
        block_age: int | None = None
        try:
            latest_block = self.web3.eth.get_block("latest")
            block_number = latest_block["number"]
            block_ts = int(latest_block["timestamp"])
            now = int(datetime.now(UTC).timestamp())
            block_age = max(0, now - block_ts)
            if block_age > self.max_block_age_seconds:
                issues.append("block_stale")
        except (KeyError, ValueError, Web3Exception) as err:
            issues.append("block_fetch_failed")
            logger.warning("relayer.health.block_fetch_failed", error=str(err))

        relayer_balance: int | None = None
        try:
            relayer_balance = self.web3.eth.get_balance(self.account.address)
            if relayer_balance < self.min_relayer_balance_wei:
                issues.append("low_balance")
        except (Web3Exception, ValueError) as err:
            issues.append("balance_fetch_failed")
            logger.warning("relayer.health.balance_fetch_failed", error=str(err))

        token_address: str | None = None
        escrow_token_balance: int | None = None
        relayer_token_balance: int | None = None
        relayer_token_allowance: int | None = None
        try:
            token_address_raw = self.escrow.functions.COLLATERAL_TOKEN().call()
            token_address = str(token_address_raw)
            token_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(token_address),
                abi=ERC20_ABI,
            )
            escrow_token_balance = token_contract.functions.balanceOf(self.escrow.address).call()
            relayer_token_balance = token_contract.functions.balanceOf(self.account.address).call()
            relayer_token_allowance = token_contract.functions.allowance(
                self.account.address, self.escrow.address
            ).call()
            if escrow_token_balance is not None and escrow_token_balance < self.min_escrow_token_balance_wei:
                issues.append("low_escrow_token_balance")
            if relayer_token_allowance is not None and relayer_token_allowance < self.min_relayer_token_allowance_wei:
                issues.append("low_relayer_token_allowance")
        except (Web3Exception, ValueError) as err:
            issues.append("token_fetch_failed")
            logger.warning("relayer.health.token_fetch_failed", error=str(err))

        escrow_owner: str | None = None
        try:
            escrow_owner = self.escrow.functions.owner().call()
            if escrow_owner is not None and str(escrow_owner).lower() != self.account.address.lower():
                issues.append("owner_mismatch")
        except (Web3Exception, ValueError) as err:
            logger.warning("relayer.health.owner_fetch_failed", error=str(err))

        status = "ok" if connected and not issues else "degraded"
        payload = {
            "status": status,
            "relayer": self.account.address,
            "escrow": self.escrow.address,
            "chainId": self.chain_id,
            "rpc": self.rpc_url,
            "latestBlock": block_number,
            "blockAgeSeconds": block_age,
            "relayerBalanceWei": relayer_balance,
            "issues": issues,
            "connected": connected,
            "escrowOwner": escrow_owner,
            "tokenAddress": token_address,
            "escrowTokenBalanceWei": escrow_token_balance,
            "relayerTokenBalanceWei": relayer_token_balance,
            "relayerTokenAllowanceWei": relayer_token_allowance,
        }
        logger.info("relayer.health", **payload)
        HEALTH_CHECKS.labels(status=status).inc()
        return payload


def build_service(
    web3: Web3,
    escrow_address: str,
    account: LocalAccount,
    chain_id: int,
    rpc_url: str,
    *,
    max_retries: int = 3,
    retry_backoff_seconds: float = 0.5,
    tx_timeout_seconds: int = 120,
    max_block_age_seconds: int = 60,
    min_relayer_balance_wei: int = 0,
    min_escrow_token_balance_wei: int = 0,
    min_relayer_token_allowance_wei: int = 0,
    fee_bump_percent: float = 0.15,
) -> RelayerService:
    escrow_addr: ChecksumAddress = web3.to_checksum_address(escrow_address)
    escrow = web3.eth.contract(address=escrow_addr, abi=COMMIT_ABI)
    return RelayerService(
        web3=web3,
        escrow=escrow,
        account=account,
        chain_id=chain_id,
        rpc_url=rpc_url,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
        tx_timeout_seconds=tx_timeout_seconds,
        max_block_age_seconds=max_block_age_seconds,
        min_relayer_balance_wei=min_relayer_balance_wei,
        min_escrow_token_balance_wei=min_escrow_token_balance_wei,
        min_relayer_token_allowance_wei=min_relayer_token_allowance_wei,
        fee_bump_percent=fee_bump_percent,
    )
