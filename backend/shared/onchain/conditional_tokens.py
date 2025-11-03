from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from web3 import Web3

_CONDITIONAL_TOKENS_ABI: List[Dict[str, Any]] = [
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
]


class ConditionalTokensClient:
    """Read resolution information from the Conditional Tokens contract."""

    def __init__(self, rpc_url: str, contract_address: str) -> None:
        self._web3 = Web3(Web3.HTTPProvider(rpc_url))
        self._contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=_CONDITIONAL_TOKENS_ABI,
        )

    def read_payout_vector(self, condition_id_hex: str, outcome_count: int) -> tuple[bool, List[int]]:
        """Return whether payouts are set and the numerators for each outcome."""
        if outcome_count < 0:
            raise ValueError("outcome_count must be non-negative")
        condition_id = Web3.to_bytes(hexstr=condition_id_hex)
        resolved = bool(self._contract.functions.payoutsAreSet(condition_id).call())
        if not resolved:
            return False, [0] * max(outcome_count, 0)
        numerators: List[int] = []
        for index in range(outcome_count):
            value = self._contract.functions.payoutNumerators(condition_id, index).call()
            numerators.append(int(value))
        return True, numerators

    def resolution_summary(
        self,
        condition_id_hex: str,
        outcomes: Sequence[str] | None,
        outcome_count_hint: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a structured summary of the payout vector for application use."""
        outcome_labels = list(outcomes) if outcomes else []
        outcome_count = len(outcome_labels)
        if outcome_count == 0 and outcome_count_hint:
            outcome_count = outcome_count_hint
        resolved, numerators = self.read_payout_vector(condition_id_hex, outcome_count)
        winners = _derive_winners(numerators, outcome_labels) if resolved else []
        return {
            "source": "conditional_tokens",
            "conditionId": condition_id_hex,
            "resolved": resolved,
            "outcomes": outcome_labels,
            "payouts": numerators,
            "winners": winners,
            "checkedAt": datetime.now(tz=timezone.utc).isoformat(),
        }


def _derive_winners(numerators: Sequence[int], outcomes: Sequence[str]) -> List[Dict[str, Any]]:
    winners: List[Dict[str, Any]] = []
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
