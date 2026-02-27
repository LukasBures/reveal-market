from __future__ import annotations

import logging
from typing import Any, cast

from eth_utils import event_abi_to_log_topic
from eth_utils.abi import ABIEvent
from web3 import Web3
from web3._utils.events import get_event_data

from shared.onchain.abi import (
    ERC20_ABI,
    MARKET_FACTORY_ABI,
    PROTOCOL_POOL_ABI,
    RELAYER_ESCROW_ABI,
    REVEAL_MARKET_ABI,
)


def _build_event_topic_map(abi: list[dict]) -> dict[str, ABIEvent]:
    topics: dict[str, ABIEvent] = {}
    for entry in abi:
        if entry.get("type") != "event":
            continue
        event_abi = cast(ABIEvent, entry)
        topic = event_abi_to_log_topic(event_abi).hex()
        topics[topic] = event_abi
    return topics


_EVENT_TOPIC_MAP: dict[str, ABIEvent] = {}
_EVENT_TOPIC_MAP.update(_build_event_topic_map(MARKET_FACTORY_ABI))
_EVENT_TOPIC_MAP.update(_build_event_topic_map(REVEAL_MARKET_ABI))
_EVENT_TOPIC_MAP.update(_build_event_topic_map(RELAYER_ESCROW_ABI))
_EVENT_TOPIC_MAP.update(_build_event_topic_map(ERC20_ABI))
_EVENT_TOPIC_MAP.update(_build_event_topic_map(PROTOCOL_POOL_ABI))
_LOGGER = logging.getLogger(__name__)


def decode_known_logs(web3: Web3, receipt: Any) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for log in getattr(receipt, "logs", []) or []:
        topics = log.get("topics") if isinstance(log, dict) else getattr(log, "topics", None)
        if not topics:
            continue
        topic0 = topics[0].hex() if hasattr(topics[0], "hex") else str(topics[0])
        event_abi = _EVENT_TOPIC_MAP.get(topic0)
        if event_abi is None:
            continue
        try:
            decoded_event = get_event_data(web3.codec, event_abi, log)
            decoded.append(
                {
                    "address": decoded_event.get("address"),
                    "event": decoded_event["event"],
                    "args": dict(decoded_event["args"]),
                    "logIndex": decoded_event.get("logIndex"),
                    "transactionHash": decoded_event.get("transactionHash"),
                }
            )
        except Exception as exc:
            _LOGGER.warning("Failed to decode log", exc_info=exc)
            continue
    return decoded
