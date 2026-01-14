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
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"}],
        "name": "FactoryPaused",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"}],
        "name": "RelayerCommitsPaused",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "relayer", "type": "address"}],
        "name": "RelayerEscrowUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "pool", "type": "address"}],
        "name": "ProtocolPoolUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "uint256", "name": "rakeBps", "type": "uint256"}],
        "name": "GlobalRakeUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "rakeBps", "type": "uint256"},
        ],
        "name": "MarketRakeSynced",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "signer", "type": "address"},
        ],
        "name": "AuthorizationSignerUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "oracle", "type": "address"},
        ],
        "name": "OracleUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "relayer", "type": "address"},
        ],
        "name": "MarketRelayerUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "liabilityCap", "type": "uint256"},
        ],
        "name": "MarketLiabilityCapUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "newDeadline", "type": "uint256"},
        ],
        "name": "MarketClaimDeadlineExtended",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "recipient", "type": "address"},
        ],
        "name": "MarketClaimsSwept",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"},
        ],
        "name": "MarketCommitsPaused",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"},
        ],
        "name": "MarketClaimsPaused",
        "type": "event",
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
            {"indexed": True, "internalType": "address", "name": "oracle", "type": "address"},
            {"indexed": False, "internalType": "bytes32", "name": "circuitHash", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "ticketSize", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "commitDeadline", "type": "uint256"},
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


def _event_map(abi: list[dict]) -> dict[str, dict]:
    return {entry["name"]: entry for entry in abi if entry.get("type") == "event"}


# Minimal verifier ABI for circuit hash checks.
VERIFIER_ABI: list[dict] = [
    {
        "inputs": [],
        "name": "circuitHash",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Minimal RevealMarket ABI surface used by the API (ticket id + state checks).
REVEAL_MARKET_ABI: list[dict] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "uint256", "name": "ticketId", "type": "uint256"},
            {"indexed": False, "internalType": "bytes32", "name": "commitment", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "totalEscrow", "type": "uint256"},
        ],
        "name": "Committed",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "internalType": "bytes32", "name": "commitmentsRoot", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "ticketCount", "type": "uint256"},
        ],
        "name": "Locked",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "uint256", "name": "winningOutcomeId", "type": "uint256"}],
        "name": "ResultPosted",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "internalType": "uint256", "name": "totalLiability", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "rakeAmount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "protocolTopUp", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "poolYes", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "poolNo", "type": "uint256"},
        ],
        "name": "Settled",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "relayer", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": True, "internalType": "uint256", "name": "ticketId", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "Claimed",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "uint256", "name": "newDeadline", "type": "uint256"}],
        "name": "ClaimDeadlineExtended",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "recipient", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "ClaimsSwept",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"}],
        "name": "CommitsPausedSet",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"}],
        "name": "ClaimsPausedSet",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "caller", "type": "address"}],
        "name": "RefundsEnabled",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "caller", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": True, "internalType": "uint256", "name": "ticketId", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "Refunded",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "signer", "type": "address"}],
        "name": "AuthorizationSignerUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "oracle", "type": "address"}],
        "name": "OracleUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "relayer", "type": "address"}],
        "name": "RelayerEscrowUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "uint256", "name": "newCap", "type": "uint256"}],
        "name": "ProtocolLiabilityCapUpdated",
        "type": "event",
    },
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
        "name": "claimDeadline",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "batchRoots",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "batchCounts",
        "outputs": [{"internalType": "uint16", "name": "", "type": "uint16"}],
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
            {"internalType": "uint256", "name": "winningOutcomeId_", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalEscrow",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalLiability",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "poolTotalYes",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "poolTotalNo",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "rakeBps",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "circuitHash",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "oracle",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "claimedTickets",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "resultPosted",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "outcomeId", "type": "uint256"}],
        "name": "postResult",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes", "name": "proof", "type": "bytes"},
            {"internalType": "uint256[10]", "name": "publicSignals", "type": "uint256[10]"},
        ],
        "name": "verifyAndSettle",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes32[]", "name": "roots", "type": "bytes32[]"},
            {"internalType": "uint16[]", "name": "counts", "type": "uint16[]"},
            {"internalType": "bytes", "name": "relayerSig", "type": "bytes"},
        ],
        "name": "lockBatches",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "bytes[]", "name": "proofs", "type": "bytes[]"},
            {"internalType": "uint256[10][]", "name": "publicSignals", "type": "uint256[10][]"},
            {"internalType": "uint16[]", "name": "batchIndexes", "type": "uint16[]"},
        ],
        "name": "verifyAndSettleBatched",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

# Minimal ABI fragments for collateral accounting checks.
ERC20_ABI: list[dict] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "owner", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "spender", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "value", "type": "uint256"},
        ],
        "name": "Approval",
        "type": "event",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

PROTOCOL_POOL_ABI: list[dict] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "cap", "type": "uint256"},
        ],
        "name": "MarketRegistered",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "oldCap", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "newCap", "type": "uint256"},
        ],
        "name": "CapUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "totalDrawn", "type": "uint256"},
        ],
        "name": "LiabilityDrawn",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "FundsReceived",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "Withdrawn",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "factory", "type": "address"}],
        "name": "MarketFactoryUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "uint256", "name": "capacity", "type": "uint256"}],
        "name": "CapacityUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"}],
        "name": "DrawsPausedSet",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"},
        ],
        "name": "MarketDrawPausedSet",
        "type": "event",
    },
    {
        "inputs": [],
        "name": "COLLATERAL_TOKEN",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "allowedMarket",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "capacity",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "consumedLiability",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "liabilityCap",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

RELAYER_ESCROW_ABI: list[dict] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "Deposited",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "Withdrawn",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "market", "type": "address"}],
        "name": "MarketRegistered",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": True, "internalType": "address", "name": "factory", "type": "address"}],
        "name": "MarketFactoryUpdated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [{"indexed": False, "internalType": "bool", "name": "paused", "type": "bool"}],
        "name": "CommitsPausedSet",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": False, "internalType": "bytes32", "name": "commitment", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "debitedFromUser", "type": "uint256"},
        ],
        "name": "CommitForwarded",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "market", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "user", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "CreditReceived",
        "type": "event",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "balances",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

MARKET_FACTORY_EVENT_MAP: dict[str, dict] = _event_map(MARKET_FACTORY_ABI)
REVEAL_MARKET_EVENT_MAP: dict[str, dict] = _event_map(REVEAL_MARKET_ABI)
ERC20_EVENT_MAP: dict[str, dict] = _event_map(ERC20_ABI)
PROTOCOL_POOL_EVENT_MAP: dict[str, dict] = _event_map(PROTOCOL_POOL_ABI)
RELAYER_ESCROW_EVENT_MAP: dict[str, dict] = _event_map(RELAYER_ESCROW_ABI)
