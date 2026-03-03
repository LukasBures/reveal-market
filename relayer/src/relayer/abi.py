COMMIT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "address", "name": "market", "type": "address"},
            {
                "components": [
                    {"internalType": "bytes32", "name": "commitment", "type": "bytes32"},
                    {"internalType": "uint256", "name": "ticketId", "type": "uint256"},
                    {"internalType": "address", "name": "user", "type": "address"},
                    {"internalType": "uint256", "name": "nonce", "type": "uint256"},
                    {"internalType": "uint256", "name": "expiry", "type": "uint256"},
                    {"internalType": "uint256", "name": "ticketValue", "type": "uint256"},
                ],
                "internalType": "struct IRevealMarket.CommitAuth",
                "name": "auth",
                "type": "tuple",
            },
            {"internalType": "bytes", "name": "signature", "type": "bytes"},
        ],
        "name": "commitOnBehalf",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "marketFactory",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "COLLATERAL_TOKEN",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

CLAIM_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "uint256", "name": "ticketId", "type": "uint256"},
            {"internalType": "uint256", "name": "outcomeId", "type": "uint256"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint256", "name": "payout", "type": "uint256"},
            {"internalType": "bytes32", "name": "salt", "type": "bytes32"},
            {"internalType": "bytes32[]", "name": "merkleProof", "type": "bytes32[]"},
        ],
        "name": "claim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

LOCK_BATCHES_ABI = [
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
    }
]
