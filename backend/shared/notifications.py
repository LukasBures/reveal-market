"""Fire-and-forget Discord notifications for market lifecycle events.

Reads ``RM_DISCORD_LIFECYCLE_WEBHOOK_URL`` and ``RM_BLOCK_EXPLORER_URL``
from the environment.  When the webhook URL is unset every call is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger("reveal_market.notifications")

_WEBHOOK_URL: <REDACTED>
_EXPLORER: str = (os.getenv("RM_BLOCK_EXPLORER_URL") or "https://horizen.calderaexplorer.xyz").rstrip("/")

_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class Event(StrEnum):
    CREATED = "created"
    COMMITTED = "committed"
    PROOF_GENERATED = "proof_generated"
    SETTLED = "settled"
    CLAIMED = "claimed"


_COLORS: dict[Event, int] = {
    Event.CREATED: 0x2ECC71,  # green
    Event.COMMITTED: 0x3498DB,  # blue
    Event.PROOF_GENERATED: 0x5B2C6F,  # indigo
    Event.SETTLED: 0xF1C40F,  # gold
    Event.CLAIMED: 0x1ABC9C,  # teal
}

_TITLES: dict[Event, str] = {
    Event.CREATED: "New Market",
    Event.COMMITTED: "New Commitment",
    Event.PROOF_GENERATED: "Proof Generated",
    Event.SETTLED: "Market Settled",
    Event.CLAIMED: "Payout Claimed",
}


# ---------------------------------------------------------------------------
# Link formatters
# ---------------------------------------------------------------------------


def addr(address: str | None) -> str:
    """Clickable block-explorer link for an address."""
    if not address:
        return "\u2014"
    short = f"{address[:6]}\u2026{address[-4:]}" if len(address) > 10 else address
    return f"[`{short}`]({_EXPLORER}/address/{address})"


def tx(tx_hash: str | None) -> str:
    """Clickable block-explorer link for a transaction."""
    if not tx_hash:
        return "\u2014"
    short = f"{tx_hash[:10]}\u2026{tx_hash[-6:]}" if len(tx_hash) > 16 else tx_hash
    return f"[`{short}`]({_EXPLORER}/tx/{tx_hash})"


def _side(outcome_id: int | None) -> str:
    if outcome_id == 0:
        return "YES"
    if outcome_id == 1:
        return "NO"
    return str(outcome_id) if outcome_id is not None else "\u2014"


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------


def _field(name: str, value: str, inline: bool = True) -> dict[str, Any]:
    return {"name": name, "value": value, "inline": inline}


def _build_embed(event: Event, **kw: Any) -> dict[str, Any]:
    desc = ""
    fields: list[dict[str, Any]] = []

    if event == Event.CREATED:
        desc = f"**{kw.get('title', '\u2014')}**"
        if kw.get("category"):
            fields.append(_field("Category", kw["category"]))
        if kw.get("oracle"):
            fields.append(_field("Oracle", addr(kw["oracle"])))
        if kw.get("market_address"):
            fields.append(_field("Contract", addr(kw["market_address"])))

    elif event == Event.COMMITTED:
        side = _side(kw.get("outcome_id"))
        amount = kw.get("stake_zen", "?")
        desc = f"**{amount} ZEN** on **{side}**\n{kw.get('title', '')}"
        if kw.get("wallet"):
            fields.append(_field("Wallet", addr(kw["wallet"])))
        if kw.get("tx_hash"):
            fields.append(_field("Tx", tx(kw["tx_hash"])))

    elif event == Event.PROOF_GENERATED:
        desc = kw.get("title", "\u2014")
        if kw.get("batch_count") is not None:
            fields.append(_field("Batches", str(kw["batch_count"])))
        if kw.get("prover_version"):
            fields.append(_field("Prover", kw["prover_version"]))
        if kw.get("market_address"):
            fields.append(_field("Contract", addr(kw["market_address"])))

    elif event == Event.SETTLED:
        winner = _side(kw.get("winning_outcome_id"))
        desc = f"Winner: **{winner}**\n{kw.get('title', '')}"
        if kw.get("tx_hash"):
            fields.append(_field("Tx", tx(kw["tx_hash"])))
        if kw.get("block_number") is not None:
            fields.append(_field("Block", str(kw["block_number"])))
        if kw.get("market_address"):
            fields.append(_field("Contract", addr(kw["market_address"])))

    elif event == Event.CLAIMED:
        payout = kw.get("payout_zen", "?")
        desc = f"**{payout} ZEN**\n{kw.get('title', '')}"
        if kw.get("wallet"):
            fields.append(_field("Wallet", addr(kw["wallet"])))
        if kw.get("tx_hash"):
            fields.append(_field("Tx", tx(kw["tx_hash"])))

    return {
        "title": _TITLES.get(event, event.value),
        "description": desc,
        "color": _COLORS.get(event, 0x95A5A6),
        "fields": fields,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _get_client() -> httpx.AsyncClient:
    global _client  # noqa: PLW0603
    if _client is None:
        _client = httpx.AsyncClient(timeout=10)
    return _client


async def _send(embed: dict[str, Any]) -> None:
    if not _WEBHOOK_URL:
        return
    try:
        await _get_client().post(_WEBHOOK_URL, json={"embeds": [embed]})
    except Exception as exc:
        logger.debug("discord lifecycle post failed: %s", exc)


def notify(event: Event, **kwargs: Any) -> None:
    """Build an embed and fire it as a background task.  Safe to call anywhere."""
    if not _WEBHOOK_URL:
        return
    embed = _build_embed(event, **kwargs)
    try:
        asyncio.get_running_loop().create_task(_send(embed))
    except RuntimeError:
        pass  # no event loop — skip silently
