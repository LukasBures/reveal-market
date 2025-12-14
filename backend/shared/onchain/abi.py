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
    {
        "inputs": [{"internalType": "uint256", "name": "marketId", "type": "uint256"}],
        "name": "marketAddress",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "marketId", "type": "uint256"}],
        "name": "predictMarketAddress",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "marketId", "type": "uint256"}],
        "name": "getMarketParams",
        "outputs": [
            {
                "components": [
                    {"internalType": "address", "name": "market", "type": "address"},
                    {"internalType": "address", "name": "oracle", "type": "address"},
                    {"internalType": "address", "name": "verifier", "type": "address"},
                    {"internalType": "bytes32", "name": "circuitHash", "type": "bytes32"},
                    {"internalType": "uint256", "name": "commitDeadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "revealDeadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "ticketSize", "type": "uint256"},
                    {"internalType": "uint256", "name": "maxCommitments", "type": "uint256"},
                    {"internalType": "address", "name": "authorizationSigner", "type": "address"},
                    {"internalType": "uint256", "name": "protocolLiabilityCap", "type": "uint256"},
                    {"internalType": "uint256", "name": "rakeBps", "type": "uint256"},
                    {"internalType": "address", "name": "relayerEscrow", "type": "address"},
                    {"internalType": "address", "name": "protocolPool", "type": "address"},
                    {"internalType": "uint256", "name": "marketId", "type": "uint256"},
                ],
                "internalType": "struct MarketFactory.MarketParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

MARKET_FACTORY_EVENT_MAP: dict[str, dict] = {
    entry["name"]: entry for entry in MARKET_FACTORY_ABI if entry["type"] == "event"
}

# Minimal RevealMarket ABI surface used by the API (ticket id + state checks).
REVEAL_MARKET_ABI: list[dict] = [
    {
        "inputs": [],
        "name": "nextTicketId",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "commitmentsRoot",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "marketId",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "marketState",
        "outputs": [
            {"internalType": "bytes32", "name": "commitmentsRoot_", "type": "bytes32"},
            {"internalType": "uint256", "name": "nextTicketId_", "type": "uint256"},
            {"internalType": "uint8", "name": "phase_", "type": "uint8"},
            {"internalType": "uint256", "name": "commitDeadline_", "type": "uint256"},
            {"internalType": "uint256", "name": "revealDeadline_", "type": "uint256"},
            {"internalType": "uint256", "name": "winningOutcomeId_", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]
