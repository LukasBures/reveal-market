from __future__ import annotations

MARKET_FACTORY_ABI: list[dict] = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "oracle", "type": "address"},
                    {"internalType": "address", "name": "verifier", "type": "address"},
                    {"internalType": "bytes32", "name": "circuitHash", "type": "bytes32"},
                    {"internalType": "uint256", "name": "commitDeadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "revealDeadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "fixedTicketSize", "type": "uint256"},
                    {"internalType": "uint256", "name": "maxCommitments", "type": "uint256"},
                    {"internalType": "address", "name": "authorizationSigner", "type": "address"},
                    {"internalType": "uint256", "name": "protocolLiabilityCap", "type": "uint256"},
                ],
                "internalType": "struct MarketFactory.CreateMarketParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "createMarket",
        "outputs": [{"internalType": "address", "name": "market", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "nextMarketId",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "uint256", "name": "marketId", "type": "uint256"},
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "address", "name": "oracle", "type": "address"},
            {"indexed": False, "internalType": "bytes32", "name": "circuitHash", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "ticketSize", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "commitDeadline", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "revealDeadline", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "liabilityCap", "type": "uint256"},
        ],
        "name": "MarketCreated",
        "type": "event",
    },
]

MARKET_FACTORY_EVENT_MAP: dict[str, dict] = {
    entry["name"]: entry for entry in MARKET_FACTORY_ABI if entry["type"] == "event"
}
