import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress, HexStr
from structlog import get_logger
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import TimeExhausted, TransactionNotFound, Web3Exception
from web3.types import BlockData, TxParams, TxReceipt, Wei

from .abi import CLAIM_ABI, COMMIT_ABI, LOCK_BATCHES_ABI
from .metrics import HEALTH_CHECKS, RPC_ERRORS, TX_LATENCY, TX_OUTCOMES
from .poseidon import BATCH_SIZE, build_batch_root, compute_leaf, int_to_hex32

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
    def __init__(
        self,
        message: str,
        *,
        nonce: int | None = None,
        kind: str = "error",
        permanent: bool = False,
    ):
        super().__init__(message)
        self.nonce = nonce
        self.kind = kind
        self.permanent = permanent


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
    preflight_mode: str = "none"
    api_base_url: str | None = None
    api_bearer_token: str | None = None
    api_timeout_seconds: int = 10
    _nonce_lock: asyncio.Lock | None = field(default=None, init=False, repr=False)

    def _get_nonce_lock(self) -> asyncio.Lock:
        if self._nonce_lock is None:
            self._nonce_lock = asyncio.Lock()
        return self._nonce_lock

    def _require_field(self, payload: Mapping[str, Any], key: str) -> Any:
        if key not in payload or payload[key] is None:
            raise TxSendError(f"{key}_missing", kind="invalid", permanent=True)
        return payload[key]

    def _require_uint(self, value: Any, key: str, *, allow_zero: bool = True) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as err:
            raise TxSendError(f"{key}_invalid", kind="invalid", permanent=True) from err
        if parsed < 0 or (not allow_zero and parsed == 0):
            raise TxSendError(f"{key}_invalid", kind="invalid", permanent=True)
        return parsed

    def _require_hex(self, value: Any, key: str, *, length_bytes: int | None = None) -> bytes:
        if not isinstance(value, str):
            raise TxSendError(f"{key}_not_string", kind="invalid", permanent=True)
        if not value.startswith("0x"):
            raise TxSendError(f"{key}_missing_0x", kind="invalid", permanent=True)
        try:
            raw = Web3.to_bytes(hexstr=cast(HexStr, value))
        except ValueError as err:
            raise TxSendError(f"{key}_invalid_hex", kind="invalid", permanent=True) from err
        if length_bytes is not None and len(raw) != length_bytes:
            raise TxSendError(f"{key}_invalid_length", kind="invalid", permanent=True)
        return raw

    def _validate_commit_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        chain_id = self._require_uint(self._require_field(payload, "chain_id"), "chain_id")
        if chain_id != self.chain_id:
            raise TxSendError(f"chain_id_mismatch:{chain_id}", kind="invalid", permanent=True)

        ticket_value = self._require_uint(
            self._require_field(payload, "ticket_value_wei"),
            "ticket_value_wei",
            allow_zero=False,
        )
        nonce = self._require_uint(self._require_field(payload, "nonce"), "nonce")
        expiry = self._require_uint(
            self._require_field(payload, "expiry"),
            "expiry",
            allow_zero=False,
        )
        if expiry <= int(time.time()):
            raise TxSendError("expiry_in_past", kind="invalid", permanent=True)

        commitment_bytes = self._require_hex(
            self._require_field(payload, "commitment"),
            "commitment",
            length_bytes=32,
        )
        signature_bytes = self._require_hex(
            self._require_field(payload, "signature"),
            "signature",
            length_bytes=65,
        )
        try:
            user_addr: ChecksumAddress = self.web3.to_checksum_address(self._require_field(payload, "user"))
            market_addr: ChecksumAddress = self.web3.to_checksum_address(self._require_field(payload, "market"))
        except ValueError as err:
            raise TxSendError("invalid_address", kind="invalid", permanent=True) from err

        return {
            "chain_id": chain_id,
            "ticket_value": ticket_value,
            "nonce": nonce,
            "expiry": expiry,
            "commitment_bytes": commitment_bytes,
            "signature_bytes": signature_bytes,
            "user_addr": user_addr,
            "market_addr": market_addr,
        }

    def _validate_claim_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        ticket_id = self._require_uint(self._require_field(payload, "ticket_id"), "ticket_id")
        outcome_id = self._require_uint(self._require_field(payload, "outcome_id"), "outcome_id")
        amount = self._require_uint(
            self._require_field(payload, "amount"),
            "amount",
            allow_zero=False,
        )
        payout = self._require_uint(
            self._require_field(payload, "payout"),
            "payout",
            allow_zero=False,
        )

        salt_value = self._require_field(payload, "salt")
        self._require_hex(salt_value, "salt", length_bytes=32)
        proof_value = self._require_field(payload, "merkle_proof")
        if not isinstance(proof_value, list):
            raise TxSendError("merkle_proof_invalid", kind="invalid", permanent=True)
        for idx, item in enumerate(proof_value):
            self._require_hex(item, f"merkle_proof[{idx}]", length_bytes=32)

        try:
            user_addr: ChecksumAddress = self.web3.to_checksum_address(self._require_field(payload, "user"))
            market_addr: ChecksumAddress = self.web3.to_checksum_address(self._require_field(payload, "market"))
        except ValueError as err:
            raise TxSendError("invalid_address", kind="invalid", permanent=True) from err

        return {
            "ticket_id": ticket_id,
            "outcome_id": outcome_id,
            "amount": amount,
            "payout": payout,
            "user_addr": user_addr,
            "market_addr": market_addr,
        }

    def _validate_lock_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tickets = payload.get("tickets")
        if not isinstance(tickets, list) or not tickets:
            raise TxSendError("tickets_missing", kind="invalid", permanent=True)
        if not payload.get("event_id") and not payload.get("market_id"):
            raise TxSendError("market_id_missing", kind="invalid", permanent=True)
        try:
            market_addr: ChecksumAddress = self.web3.to_checksum_address(self._require_field(payload, "market"))
        except ValueError as err:
            raise TxSendError("invalid_address", kind="invalid", permanent=True) from err

        relayer_sig = payload.get("relayer_sig")
        relayer_sig_bytes = b""
        if relayer_sig is not None:
            relayer_sig_bytes = self._require_hex(relayer_sig, "relayer_sig")
        return {
            "market_addr": market_addr,
            "tickets": tickets,
            "relayer_sig": relayer_sig_bytes,
        }

    def _build_batch_roots(self, tickets: list[Mapping[str, Any]]) -> tuple[list[str], list[int], int]:
        batch_map: dict[int, dict[int, int]] = {}
        for idx, ticket in enumerate(tickets):
            if not isinstance(ticket, Mapping):
                raise TxSendError("tickets_invalid", kind="invalid", permanent=True)
            ticket_id = self._require_uint(ticket.get("ticket_id"), f"tickets[{idx}].ticket_id")
            outcome_id = self._require_uint(ticket.get("outcome_id"), f"tickets[{idx}].outcome_id")
            amount = self._require_uint(ticket.get("amount"), f"tickets[{idx}].amount", allow_zero=True)
            payout = self._require_uint(ticket.get("payout"), f"tickets[{idx}].payout", allow_zero=True)
            try:
                user_addr: ChecksumAddress = self.web3.to_checksum_address(self._require_field(ticket, "user"))
            except ValueError as err:
                raise TxSendError("invalid_address", kind="invalid", permanent=True) from err
            salt_raw = self._require_field(ticket, "salt")
            self._require_hex(salt_raw, f"tickets[{idx}].salt", length_bytes=32)

            computed_leaf = compute_leaf(ticket_id, outcome_id, amount, payout, user_addr, salt_raw)
            leaf_raw = ticket.get("leaf")
            if leaf_raw is not None:
                leaf_bytes = self._require_hex(leaf_raw, f"tickets[{idx}].leaf", length_bytes=32)
                if int.from_bytes(leaf_bytes, "big") != computed_leaf:
                    raise TxSendError("leaf_mismatch", kind="invalid", permanent=True)

            batch_index = ticket_id // BATCH_SIZE
            index_in_batch = ticket_id % BATCH_SIZE
            batch = batch_map.setdefault(batch_index, {})
            if index_in_batch in batch:
                raise TxSendError("ticket_index_duplicate", kind="invalid", permanent=True)
            batch[index_in_batch] = computed_leaf

        if not batch_map:
            raise TxSendError("tickets_missing", kind="invalid", permanent=True)

        max_batch_index = max(batch_map.keys())
        roots: list[str] = []
        counts: list[int] = []
        total_count = 0
        for batch_index in range(max_batch_index + 1):
            if batch_index not in batch_map:
                raise TxSendError("batch_index_gap", kind="invalid", permanent=True)
            batch = batch_map[batch_index]
            count = max(batch.keys()) + 1
            if count > BATCH_SIZE:
                raise TxSendError("batch_size_exceeded", kind="invalid", permanent=True)
            if len(batch) != count:
                raise TxSendError("batch_index_gap", kind="invalid", permanent=True)
            try:
                leaves = [batch[i] for i in range(count)]
            except KeyError as err:
                raise TxSendError("batch_index_gap", kind="invalid", permanent=True) from err
            root_int = build_batch_root(leaves)
            roots.append(int_to_hex32(root_int))
            counts.append(count)
            total_count += count
        if total_count != len(tickets):
            raise TxSendError("batch_count_mismatch", kind="invalid", permanent=True)
        return roots, counts, total_count

    def validate_commit_payload(self, payload: Mapping[str, Any]) -> None:
        self._validate_commit_payload(payload)

    def validate_claim_payload(self, payload: Mapping[str, Any]) -> None:
        self._validate_claim_payload(payload)

    def validate_lock_payload(self, payload: Mapping[str, Any]) -> None:
        self._validate_lock_payload(payload)

    async def _build_base_tx(
        self, value: int = 0, nonce_override: int | None = None, bump_factor: float = 1.0
    ) -> TxParams:
        nonce = nonce_override
        if nonce is None:
            nonce = await asyncio.to_thread(self.web3.eth.get_transaction_count, self.account.address, "pending")
        base: dict[str, int | str | Wei] = {
            "from": self.account.address,
            "nonce": nonce,
            "value": cast(Wei, value),
            "chainId": self.chain_id,
        }
        fee_params = await self._build_fee_params(bump_factor)
        return cast(TxParams, {**base, **fee_params})

    async def _build_fee_params(self, bump_factor: float = 1.0) -> dict[str, int]:
        def _calc() -> dict[str, int]:
            try:
                latest_block: BlockData = self.web3.eth.get_block("latest")
                base_fee = latest_block.get("baseFeePerGas")
                if base_fee is not None:
                    priority_fee = int(self.web3.eth.max_priority_fee * bump_factor)
                    max_fee = int(base_fee * 2 * bump_factor + priority_fee)
                    return {"maxPriorityFeePerGas": priority_fee, "maxFeePerGas": max_fee}
            except (Web3Exception, ValueError, TypeError) as err:
                logger.warning("relayer.fee_params.fallback", error=str(err))
            gas_price = int(self.web3.eth.gas_price * bump_factor)
            return {"gasPrice": gas_price}

        return await asyncio.to_thread(_calc)

    async def _send_and_wait(self, tx: TxParams, action: str) -> dict[str, str | int]:
        last_err: Exception | None = None
        start = time.perf_counter()
        nonce_value = tx.get("nonce")
        if nonce_value is None:
            raise TxSendError("nonce missing from transaction")
        nonce_used = cast(int, nonce_value)
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    f"relayer.{action}.attempt",
                    attempt=attempt,
                    nonce=nonce_used,
                    to=tx.get("to"),
                    value=int(tx.get("value") or 0),
                    gas_price=tx.get("gasPrice"),
                    max_fee_per_gas=tx.get("maxFeePerGas"),
                    max_priority_fee_per_gas=tx.get("maxPriorityFeePerGas"),
                )
                signed = await asyncio.to_thread(self.account.sign_transaction, cast(dict[str, Any], tx))
                send_timeout = min(self.tx_timeout_seconds, 30)
                try:
                    raw_tx = self._raw_tx_bytes(signed)
                    tx_hash = await asyncio.wait_for(
                        asyncio.to_thread(self.web3.eth.send_raw_transaction, raw_tx),
                        timeout=send_timeout,
                    )
                except TimeoutError as err:
                    raise TxSendError(f"{action}_send_timeout", nonce=nonce_used, kind="timeout") from err
                logger.info(
                    f"relayer.{action}.broadcast",
                    attempt=attempt,
                    tx_hash=tx_hash.hex(),
                    nonce=nonce_used,
                )
                receipt = await self._poll_receipt(tx_hash, action, nonce_used, start, attempt=attempt)
                status = int(receipt["status"])
                tx_hex = tx_hash.hex()
                if not tx_hex.startswith("0x"):
                    tx_hex = f"0x{tx_hex}"
                return {"txHash": tx_hex, "status": status, "nonce": nonce_used}
            except TxSendError as err:
                last_err = err
                outcome = err.kind
                if err.kind == "timeout":
                    logger.warning(
                        f"relayer.{action}.timeout",
                        attempt=attempt,
                        timeout=self.tx_timeout_seconds,
                        error=f"{type(err).__name__}:{err}",
                        nonce=nonce_used,
                    )
                elif err.kind == "reverted":
                    logger.warning(
                        f"relayer.{action}.reverted",
                        attempt=attempt,
                        error=f"{type(err).__name__}:{err}",
                        nonce=nonce_used,
                    )
                else:
                    logger.warning(
                        f"relayer.{action}.error",
                        attempt=attempt,
                        error=f"{type(err).__name__}:{err}",
                        nonce=nonce_used,
                    )
                TX_OUTCOMES.labels(action=action, outcome=outcome).inc()
                if err.permanent:
                    break
            except TimeExhausted as err:
                last_err = err
                logger.warning(
                    f"relayer.{action}.timeout",
                    attempt=attempt,
                    timeout=self.tx_timeout_seconds,
                    error=f"{type(err).__name__}:{err}",
                    nonce=nonce_used,
                )
                TX_OUTCOMES.labels(action=action, outcome="timeout").inc()
            except (Web3Exception, ValueError, Exception) as err:
                last_err = err
                logger.warning(
                    f"relayer.{action}.error",
                    attempt=attempt,
                    error=f"{type(err).__name__}:{err}",
                    nonce=nonce_used,
                )
                TX_OUTCOMES.labels(action=action, outcome="error").inc()

            await asyncio.sleep(self.retry_backoff_seconds * attempt)

        logger.error(f"relayer.{action}.failed", error=str(last_err))
        TX_OUTCOMES.labels(action=action, outcome="failed").inc()
        if isinstance(last_err, TxSendError):
            raise last_err
        raise TxSendError(str(last_err) if last_err else f"{action} failed without error", nonce=nonce_used)

    @staticmethod
    def _raw_tx_bytes(signed_tx) -> bytes:
        # Prefer snake_case (newer eth-account/web3) and fall back to camelCase for compatibility.
        raw_tx = getattr(signed_tx, "raw_transaction", None)
        if raw_tx is None:
            raw_tx = getattr(signed_tx, "rawTransaction", None)
        if raw_tx is None:
            raise TxSendError("signed_tx_missing_raw_transaction")
        return raw_tx

    async def _poll_receipt(self, tx_hash, action: str, nonce_used: int, start: float, *, attempt: int) -> TxReceipt:
        """Poll for a receipt with a hard timeout so jobs do not hang forever."""

        deadline = start + self.tx_timeout_seconds
        poll_interval = min(5.0, max(0.5, self.tx_timeout_seconds / 30))
        single_call_timeout = max(5.0, min(15.0, self.tx_timeout_seconds / 2))
        last_err: Exception | None = None
        while True:
            now = time.perf_counter()
            if now >= deadline:
                raise TxSendError(f"{action}_receipt_timeout", nonce=nonce_used, kind="timeout")
            try:
                receipt: TxReceipt = await asyncio.wait_for(
                    asyncio.to_thread(self.web3.eth.get_transaction_receipt, tx_hash),
                    timeout=single_call_timeout,
                )
                status = int(receipt["status"])
                if status == 0:
                    logger.warning(
                        f"relayer.{action}.revert",
                        tx_hash=tx_hash.hex(),
                        attempt=attempt,
                    )
                    raise TxSendError("tx_reverted", nonce=nonce_used, kind="reverted", permanent=True)
                logger.info(
                    f"relayer.{action}.sent",
                    tx_hash=tx_hash.hex(),
                    status=status,
                    attempt=attempt,
                )
                TX_OUTCOMES.labels(action=action, outcome="success").inc()
                TX_LATENCY.labels(action=action).observe(time.perf_counter() - start)
                return receipt
            except TransactionNotFound as err:  # Not mined yet.
                last_err = err
            except (Web3Exception, ValueError) as err:
                last_err = err
            except TimeoutError as err:
                last_err = err

            if last_err is not None:
                logger.info(
                    f"relayer.{action}.waiting",
                    tx_hash=tx_hash.hex(),
                    attempt=attempt,
                    error=f"{type(last_err).__name__}:{last_err}",
                    poll_interval=poll_interval,
                )
            await asyncio.sleep(poll_interval)

    async def _preflight_tx(self, tx: TxParams, action: str) -> None:
        if self.preflight_mode == "none":
            return
        if self.preflight_mode in ("call", "both"):
            try:
                await asyncio.to_thread(self.web3.eth.call, tx)
            except (Web3Exception, ValueError, Exception) as err:
                logger.warning("relayer.preflight.call_failed", action=action, error=str(err))
                raise TxSendError("preflight_call_failed", kind="invalid", permanent=True) from err
        if self.preflight_mode in ("estimate", "both"):
            try:
                await asyncio.to_thread(self.web3.eth.estimate_gas, tx)
            except (Web3Exception, ValueError, Exception) as err:
                logger.warning("relayer.preflight.estimate_failed", action=action, error=str(err))
                raise TxSendError("preflight_estimate_failed", kind="invalid", permanent=True) from err

    async def commit(
        self, payload: Mapping[str, Any], *, nonce_override: int | None = None, bump_factor: float = 1.0
    ) -> dict[str, str | int]:
        validation = self._validate_commit_payload(payload)
        ticket_value = validation["ticket_value"]
        chain_id = validation["chain_id"]
        commitment = validation["commitment_bytes"]
        signature_bytes = validation["signature_bytes"]
        user_addr = validation["user_addr"]
        market_addr = validation["market_addr"]
        auth = (
            commitment,
            user_addr,
            validation["nonce"],
            validation["expiry"],
            ticket_value,
        )
        logger.info(
            "relayer.commit.prepare",
            user=payload.get("user"),
            market=payload.get("market"),
            nonce=auth[2],
            expiry=auth[3],
            value=0,
            chain_id=chain_id,
            bump_factor=bump_factor,
            nonce_override=nonce_override,
        )
        async with self._get_nonce_lock():
            base_tx = await self._build_base_tx(0, nonce_override, bump_factor)
            tx = self.escrow.functions.commitOnBehalf(
                user_addr,
                market_addr,
                auth,
                signature_bytes,
            ).build_transaction(base_tx)
            await self._preflight_tx(tx, "commit")
            return await self._send_and_wait(tx, "commit")

    async def claim(
        self, payload: Mapping[str, Any], *, nonce_override: int | None = None, bump_factor: float = 1.0
    ) -> dict[str, str | int]:
        validation = self._validate_claim_payload(payload)
        market_addr = validation["market_addr"]
        market = self.web3.eth.contract(address=market_addr, abi=CLAIM_ABI)
        logger.info(
            "relayer.claim.prepare",
            user=payload.get("user"),
            market=payload.get("market"),
            ticket_id=validation["ticket_id"],
            outcome_id=validation["outcome_id"],
            amount=validation["amount"],
            payout=validation["payout"],
            bump_factor=bump_factor,
            nonce_override=nonce_override,
        )
        async with self._get_nonce_lock():
            base_tx = await self._build_base_tx(0, nonce_override, bump_factor)
            tx = market.functions.claim(
                validation["user_addr"],
                validation["ticket_id"],
                validation["outcome_id"],
                validation["amount"],
                validation["payout"],
                payload["salt"],
                payload["merkle_proof"],
            ).build_transaction(base_tx)
            await self._preflight_tx(tx, "claim")
            return await self._send_and_wait(tx, "claim")

    async def lock_batches(
        self, payload: Mapping[str, Any], *, nonce_override: int | None = None, bump_factor: float = 1.0
    ) -> dict[str, str | int]:
        validation = self._validate_lock_payload(payload)
        market_addr = validation["market_addr"]
        roots, counts, total_count = self._build_batch_roots(validation["tickets"])
        if isinstance(payload, dict):
            payload["batch_roots"] = roots
            payload["batch_counts"] = counts
            payload["commitments_count"] = total_count
            payload["merkle_root"] = roots[0] if len(roots) == 1 else None

        market = self.web3.eth.contract(address=market_addr, abi=LOCK_BATCHES_ABI)
        relayer_sig = validation["relayer_sig"]
        logger.info(
            "relayer.lock_batches.prepare",
            market=payload.get("market"),
            batch_count=len(roots),
            commitments_count=total_count,
            bump_factor=bump_factor,
            nonce_override=nonce_override,
        )
        async with self._get_nonce_lock():
            base_tx = await self._build_base_tx(0, nonce_override, bump_factor)
            tx = market.functions.lockBatches(roots, counts, relayer_sig).build_transaction(base_tx)
            await self._preflight_tx(tx, "lock_batches")
            return await self._send_and_wait(tx, "lock_batches")

    async def health(self) -> dict[str, Any]:
        issues: list[str] = []
        rpc_timeout = 2.0

        async def _call(label: str, func, *args):
            start = time.perf_counter()
            try:
                return await asyncio.wait_for(asyncio.to_thread(func, *args), timeout=rpc_timeout)
            except (TimeoutError, Web3Exception, ValueError) as err:
                if label not in issues:
                    issues.append(label)
                error_type = type(err).__name__
                RPC_ERRORS.labels(label=label, error_type=error_type).inc()
                logger.warning(
                    f"relayer.health.{label}",
                    error=str(err),
                    error_type=error_type,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                )
                return None

        connected_result, block_data, relayer_balance_raw, token_address_raw, escrow_owner = await asyncio.gather(
            _call("connection_failed", self.web3.is_connected),
            _call("block_fetch_failed", self.web3.eth.get_block, "latest"),
            _call("balance_fetch_failed", self.web3.eth.get_balance, self.account.address),
            _call("token_fetch_failed", self.escrow.functions.COLLATERAL_TOKEN().call),
            _call("owner_fetch_failed", self.escrow.functions.owner().call),
        )
        connected = bool(connected_result)

        block_number: int | None = None
        block_age: int | None = None
        if block_data is not None:
            try:
                block_number = block_data["number"]
                block_ts = int(block_data["timestamp"])
                now = int(datetime.now(UTC).timestamp())
                block_age = max(0, now - block_ts)
                if block_age > self.max_block_age_seconds:
                    issues.append("block_stale")
            except (KeyError, TypeError, ValueError) as err:
                if "block_fetch_failed" not in issues:
                    issues.append("block_fetch_failed")
                logger.warning("relayer.health.block_fetch_failed", error=str(err))

        relayer_balance: int | None = None
        if relayer_balance_raw is not None:
            relayer_balance = int(relayer_balance_raw)
            if relayer_balance < self.min_relayer_balance_wei:
                issues.append("low_balance")

        token_address: str | None = None
        escrow_token_balance: int | None = None
        relayer_token_balance: int | None = None
        relayer_token_allowance: int | None = None
        if token_address_raw:
            try:
                token_address = str(token_address_raw)
                token_contract = self.web3.eth.contract(
                    address=self.web3.to_checksum_address(token_address),
                    abi=ERC20_ABI,
                )
                (
                    escrow_token_balance,
                    relayer_token_balance,
                    relayer_token_allowance,
                ) = await asyncio.gather(
                    _call("token_fetch_failed", token_contract.functions.balanceOf(self.escrow.address).call),
                    _call("token_fetch_failed", token_contract.functions.balanceOf(self.account.address).call),
                    _call(
                        "token_fetch_failed",
                        token_contract.functions.allowance(self.account.address, self.escrow.address).call,
                    ),
                )
                if escrow_token_balance is not None and escrow_token_balance < self.min_escrow_token_balance_wei:
                    issues.append("low_escrow_token_balance")
                if (
                    relayer_token_allowance is not None
                    and relayer_token_allowance < self.min_relayer_token_allowance_wei
                ):
                    issues.append("low_relayer_token_allowance")
            except (Web3Exception, ValueError) as err:
                if "token_fetch_failed" not in issues:
                    issues.append("token_fetch_failed")
                logger.warning("relayer.health.token_fetch_failed", error=str(err))

        if escrow_owner is not None and str(escrow_owner).lower() != self.account.address.lower():
            issues.append("owner_mismatch")

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

    async def push_commit_ingest(self, payload: Mapping[str, Any], *, tx_hash: str | None = None) -> None:
        """Best-effort push of commitment metadata to the API ingest endpoint."""

        if not self.api_base_url:
            return
        event_id = payload.get("event_id") or payload.get("market_id")
        required = {
            "commitment": payload.get("commitment"),
            "user": payload.get("user"),
            "outcome_id": payload.get("outcome_id"),
            "amount_wei": payload.get("amount_wei"),
            "payout_wei": payload.get("payout_wei"),
            "salt": payload.get("salt"),
            "ticket_id": payload.get("ticket_id"),
        }
        missing = [
            field
            for field, value in required.items()
            if value is None or (isinstance(value, str) and not value.strip())
        ]
        if not event_id:
            missing.append("event_id")
        if missing:
            logger.warning(
                "relayer.ingest.commit_skipped",
                market=payload.get("market"),
                missing_fields=missing,
            )
            return
        ticket = {
            "ticketHash": required["commitment"],
            "leaf": required["commitment"],
            "user_address": required["user"],
            "outcomeId": required["outcome_id"],
            "amount": required["amount_wei"],
            "payout": required["payout_wei"],
            "salt": required["salt"],
            "merkleIndex": required["ticket_id"],
            "merklePath": payload.get("merkle_path") or [],
            "txHash": tx_hash,
        }
        body = {"event_id": event_id, "tickets": [ticket]}
        headers = {}
        if self.api_bearer_token:
            headers["Authorization"] = f"Bearer {self.api_bearer_token}"
        try:
            async with httpx.AsyncClient(timeout=self.api_timeout_seconds) as client:
                resp = await client.post(f"{self.api_base_url}/commitments/sync", json=body, headers=headers)
            logger.info(
                "relayer.ingest.commit",
                status=resp.status_code,
                event_id=event_id,
                market=payload.get("market"),
                tx_hash=tx_hash,
            )
        except Exception as err:  # pragma: no cover - best-effort ingest
            logger.warning("relayer.ingest.commit_failed", error=str(err), market=payload.get("market"))

    async def push_settlement_ingest(self, payload: Mapping[str, Any], *, tx_hash: str | None = None) -> None:
        """Best-effort push of settlement snapshot to the API ingest endpoint."""

        if not self.api_base_url:
            return
        market_id = payload.get("market_id") or payload.get("event_id") or payload.get("market")
        if not market_id:
            logger.warning(
                "relayer.ingest.settlement_skipped",
                market=payload.get("market"),
                reason="market_id_missing",
            )
            return
        body = {
            "event_id": market_id,
            "market_id": market_id,
            "merkleRoot": payload.get("merkle_root"),
            "commitmentsCount": payload.get("commitments_count"),
            "batchRoots": payload.get("batch_roots"),
            "batchCounts": payload.get("batch_counts"),
            "poolTotalYes": payload.get("pool_total_yes"),
            "poolTotalNo": payload.get("pool_total_no"),
            "totalEscrow": payload.get("total_escrow"),
            "totalLiability": payload.get("total_liability"),
            "rakeBps": payload.get("rake_bps"),
            "proofRequestId": payload.get("proof_request_id"),
        }
        headers = {}
        if self.api_bearer_token:
            headers["Authorization"] = f"Bearer {self.api_bearer_token}"
        try:
            async with httpx.AsyncClient(timeout=self.api_timeout_seconds) as client:
                resp = await client.post(f"{self.api_base_url}/settlements/ingest", json=body, headers=headers)
            logger.info(
                "relayer.ingest.settlement",
                status=resp.status_code,
                market_id=market_id,
                tx_hash=tx_hash,
            )
        except Exception as err:  # pragma: no cover - best-effort ingest
            logger.warning("relayer.ingest.settlement_failed", error=str(err), market=market_id)


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
    preflight_mode: str = "none",
    api_base_url: str | None = None,
    api_bearer_token: str | None = None,
    api_timeout_seconds: int = 10,
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
        preflight_mode=preflight_mode,
        api_base_url=api_base_url,
        api_bearer_token=api_bearer_token,
        api_timeout_seconds=api_timeout_seconds,
    )
