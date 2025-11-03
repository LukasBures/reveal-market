from __future__ import annotations

from typing import Dict, List

MARKET_FACTORY_ABI: List[dict] = [
    {
        "inputs": [
            {"internalType": "string", "name": "eventId", "type": "string"},
            {"internalType": "uint256", "name": "commitDeadline", "type": "uint256"},
            {"internalType": "uint256", "name": "revealDeadline", "type": "uint256"},
            {"internalType": "address", "name": "oracle", "type": "address"},
            {"internalType": "address", "name": "collateral", "type": "address"},
            {"internalType": "uint256", "name": "rakeBpsOverride", "type": "uint256"},
        ],
        "name": "createMarket",
        "outputs": [{"internalType": "address", "name": "market", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getMarkets",
        "outputs": [{"internalType": "address[]", "name": "", "type": "address[]"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": True, "internalType": "string", "name": "eventId", "type": "string"},
            {"indexed": False, "internalType": "uint256", "name": "commitDeadline", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "revealDeadline", "type": "uint256"},
            {"indexed": False, "internalType": "address", "name": "collateral", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "rakeBps", "type": "uint256"},
        ],
        "name": "MarketCreated",
        "type": "event",
    },
]

MARKET_FACTORY_EVENT_MAP: Dict[str, dict] = {
    entry["name"]: entry for entry in MARKET_FACTORY_ABI if entry["type"] == "event"
}
