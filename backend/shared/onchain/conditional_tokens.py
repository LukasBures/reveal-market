from __future__ import annotations

from collections.abc import Sequence
from typing import Any


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
