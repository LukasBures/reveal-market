from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from web3 import Web3
from web3.exceptions import Web3Exception
from web3.types import HexStr

_CONDITIONAL_TOKENS_ABI: list[dict[str, Any]] = [
    {
        "name": "payoutsAreSet",
        "outputs": [{"type": "bool"}],
        "inputs": [{"name": "conditionId", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "name": "payoutNumerators",
        "outputs": [{"type": "uint256"}],
        "inputs": [
            {"name": "conditionId", "type": "bytes32"},
            {"name": "index", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "conditionId", "type": "bytes32"},
            {"indexed": True, "name": "oracle", "type": "address"},
            {"indexed": True, "name": "questionId", "type": "bytes32"},
            {"indexed": False, "name": "payoutNumerators", "type": "uint256[]"},
        ],
        "name": "ConditionResolution",
        "type": "event",
    },
]


class ConditionalTokensClient:
    """Read resolution information from the Conditional Tokens contract."""

    def __init__(self, rpc_url: str, contract_address: str) -> None:
        self._web3 = Web3(Web3.HTTPProvider(rpc_url))
        self._contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=_CONDITIONAL_TOKENS_ABI,
        )

    def read_payout_vector(self, condition_id_hex: str, outcome_count: int) -> tuple[bool, list[int]]:
        """Return whether payouts are set and the numerators for each outcome."""
        if outcome_count < 0:
            raise ValueError("outcome_count must be non-negative")
        condition_id = Web3.to_bytes(hexstr=cast(HexStr, condition_id_hex))
        resolved = bool(self._contract.functions.payoutsAreSet(condition_id).call())
        if not resolved:
            return False, [0] * max(outcome_count, 0)
        numerators: list[int] = []
        for index in range(outcome_count):
            value = self._contract.functions.payoutNumerators(condition_id, index).call()
            numerators.append(int(value))
        return True, numerators

    def resolution_summary(
        self,
        condition_id_hex: str,
        outcomes: Sequence[str] | None,
        outcome_count_hint: int | None = None,
    ) -> dict[str, Any]:
        """Return a structured summary of the payout vector for application use."""
        outcome_labels = list(outcomes) if outcomes else []
        outcome_count = len(outcome_labels)
        if outcome_count == 0 and outcome_count_hint:
            outcome_count = outcome_count_hint
        resolved, numerators = self.read_payout_vector(condition_id_hex, outcome_count)
        metadata = self._fetch_resolution_event(condition_id_hex) if resolved else {}
        payouts = metadata.get("payoutNumerators") or numerators
        winners = _derive_winners(payouts, outcome_labels) if resolved else []
        checked_at = datetime.now(tz=UTC)
        return {
            "source": "conditional_tokens",
            "conditionId": condition_id_hex,
            "resolved": resolved,
            "outcomes": outcome_labels,
            "payouts": payouts,
            "winners": winners,
            "checkedAt": checked_at,
            "oracle": metadata.get("oracle"),
            "questionId": metadata.get("questionId"),
            "transactionHash": metadata.get("transactionHash"),
            "blockNumber": metadata.get("blockNumber"),
            "blockTimestamp": metadata.get("blockTimestamp"),
        }

    def _fetch_resolution_event(self, condition_id_hex: str) -> dict[str, Any]:
        condition_bytes = Web3.to_bytes(hexstr=cast(HexStr, condition_id_hex))
        event = self._contract.events.ConditionResolution()
        try:
            logs = event.get_logs(
                argument_filters={"conditionId": condition_bytes},
                fromBlock=0,
                toBlock="latest",
            )
        except (Web3Exception, ValueError, TypeError):  # pragma: no cover - defensive
            return {}
        if not logs:
            return {}
        latest = logs[-1]
        block_number = int(latest["blockNumber"])
        block = self._web3.eth.get_block(block_number)
        timestamp = datetime.fromtimestamp(block["timestamp"], tz=UTC)
        args = latest["args"]
        question_id = args.get("questionId")
        question_id_hex = question_id.hex() if isinstance(question_id, (bytes, bytearray)) else None
        return {
            "oracle": args.get("oracle"),
            "questionId": question_id_hex,
            "transactionHash": latest["transactionHash"].hex(),
            "blockNumber": block_number,
            "blockTimestamp": timestamp,
            "payoutNumerators": list(args.get("payoutNumerators", [])),
        }


def _derive_winners(numerators: Sequence[int], outcomes: Sequence[str]) -> list[dict[str, Any]]:
    winners: list[dict[str, Any]] = []
    if not numerators:
        return winners
    max_value = max(numerators)
    if max_value <= 0:
        return winners
    for index, value in enumerate(numerators):
        if value == max_value and value > 0:
            label = outcomes[index] if index < len(outcomes) else None
            winners.append({"index": index, "label": label, "payout": int(value)})
    return winners
