#!/usr/bin/env python3
"""Production E2E test: Create market, commit YES+NO, let worker settle, then claim.

This script runs INSIDE the API container with access to the DB and on-chain.
It creates a real market, makes real commitments, and lets the worker handle
lockBatches → postResult → proof generation → verifyAndSettle → claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from datetime import UTC, datetime

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import HTTPProvider, Web3

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RPC_URL = os.getenv("RM_RPC_URL", "https://horizen.calderachain.xyz/http")
CHAIN_ID = int(os.getenv("RM_CHAIN_ID", "26514"))

# Contract addresses
ZEN_TOKEN = os.getenv("ZEN_TOKEN_ADDRESS", "0x57da2D504bf8b83Ef304759d9f2648522D7a9280")  # noqa: S105
FACTORY = os.getenv("RM_FACTORY_ADDRESS", "0x3144B525Ffbb99dF298E9B5a589011cF423b54a3")
PROTOCOL_POOL = os.getenv("RM_PROTOCOL_POOL_ADDRESS", "0x3C8fC2C4bbe255ED8A8A343239a5EC8c016686B8")
RELAYER_ESCROW = os.getenv("RM_RELAYER_ESCROW_ADDRESS", "0x5613c11E960950434444BA0580D9998F8540CfeD")
VERIFIER = os.getenv("RM_VERIFIER_ADDRESS", "0x568c9395073D8132692Be68e8De0e859b7f05c33")
ORACLE_ADDRESS = os.getenv("RM_ORACLE_ADDRESS", "0x9b99e6f210f3FB870016aA42BaF5002D08e3A6e3")
AUTH_SIGNER_ADDRESS = os.getenv("RM_AUTHORIZATION_SIGNER", "0xA2A0b13f53FE25E5ef9B1267D1C064d7A5BD4277")
CIRCUIT_HASH = "0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157"

# Private keys (from environment — never hardcode)
DEPLOYER_KEY = os.environ["DEPLOYER_KEY"]
ORACLE_KEY = os.environ["RM_SETTLEMENT_SIGNER_PRIVATE_KEY"]
AUTH_SIGNER_KEY = os.environ["RM_AUTHORIZATION_SIGNER_PRIVATE_KEY"]
RELAYER_KEY = os.environ["RM_RELAYER_PRIVATE_KEY"]
USER_KEY = os.environ["E2E_USER_PRIVATE_KEY"]
USER_ADDRESS = Account.from_key(USER_KEY).address

# DB connection
DB_URL = os.environ.get("RM_DATABASE_URL", "")

# Service URLs (inside docker network)
API_URL = "http://localhost:8000"
INTERNAL_SECRET =<REDACTED>

# Constants
BATCH_SIZE = 256
MERKLE_DEPTH = 8
FIELD_MODULUS = 21888242871839275222246405745257275088548364400416034343698204186575808495617
TICKET_SIZE = 1 * 10**18  # 1 ZEN
MAX_COMMITMENTS = 256
LIABILITY_CAP = 3 * 10**18  # 3 ZEN (fits in 5.08 pool)
COMMIT_DEADLINE_SECS = 90  # seconds from now

# ABIs
FACTORY_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "oracle", "type": "address"},
                    {"name": "verifier", "type": "address"},
                    {"name": "circuitHash", "type": "bytes32"},
                    {"name": "commitDeadline", "type": "uint256"},
                    {"name": "fixedTicketSize", "type": "uint256"},
                    {"name": "maxCommitments", "type": "uint256"},
                    {"name": "authorizationSigner", "type": "address"},
                    {"name": "protocolLiabilityCap", "type": "uint256"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "createMarket",
        "outputs": [{"name": "market", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "nextMarketId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "marketId", "type": "uint256"}],
        "name": "marketAddress",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "globalRakeBps",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

MARKET_ABI = [
    {
        "inputs": [],
        "name": "phase",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "nextTicketId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "ticketSize",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "commitDeadline",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "winningOutcomeId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "resultPosted",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "rakeBps",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalEscrow",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "marketId",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "oracle",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "maxCommitments",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "ticketId", "type": "uint256"}],
        "name": "commitmentAt",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "i", "type": "uint256"}],
        "name": "batchRoots",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "batchIndex", "type": "uint16"}],
        "name": "batchProofVerified",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "ticketId", "type": "uint256"}],
        "name": "claimedTickets",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ESCROW_ABI = [
    {
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "market", "type": "address"},
            {
                "name": "auth",
                "type": "tuple",
                "components": [
                    {"name": "commitment", "type": "bytes32"},
                    {"name": "ticketId", "type": "uint256"},
                    {"name": "user", "type": "address"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "expiry", "type": "uint256"},
                    {"name": "ticketValue", "type": "uint256"},
                ],
            },
            {"name": "signature", "type": "bytes"},
        ],
        "name": "commitOnBehalf",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_ABI = [
    {
        "inputs": [{"name": "a", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ---------------------------------------------------------------------------
# Poseidon (circuit-compatible, BN254)
# ---------------------------------------------------------------------------
# Import poseidon — try multiple locations
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
import importlib.util as _ilu  # noqa: E402

_poseidon_paths = [
    "/app/shared/poseidon.py",  # inside API container
    "/worker/shared/poseidon.py",  # inside worker container
    os.path.join(SCRIPTS_DIR, "poseidon.py"),
]
_poseidon = None
for _pp in _poseidon_paths:
    if os.path.exists(_pp):
        _spec = _ilu.spec_from_file_location("poseidon", _pp)
        if _spec and _spec.loader:
            _poseidon = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_poseidon)
            break
if _poseidon is None:
    raise ImportError(f"Cannot find poseidon.py in {_poseidon_paths}")
poseidon_t3 = _poseidon.poseidon_t3
_compute_leaf = _poseidon.compute_leaf


def compute_leaf(ticket_id: int, outcome_id: int, amount: int, payout: int, user_int: int, salt_int: int) -> int:
    """Compute commitment leaf using shared Poseidon implementation."""
    return _compute_leaf(ticket_id, outcome_id, amount, payout, user_int, salt_int)


def address_to_field(addr: str) -> int:
    return int(addr, 16)


def build_merkle_tree(leaves_int: list[int], depth: int = MERKLE_DEPTH, pad_to: int = BATCH_SIZE) -> list[list[int]]:
    padded = leaves_int + [0] * (pad_to - len(leaves_int))
    levels = [padded]
    current = padded
    for _ in range(depth):
        next_level = []
        for i in range(0, len(current), 2):
            next_level.append(poseidon_t3(current[i], current[i + 1]))
        levels.append(next_level)
        current = next_level
    return levels


def extract_merkle_proof(tree_levels: list[list[int]], leaf_index: int) -> list[str]:
    proof = []
    idx = leaf_index
    for level in tree_levels[:-1]:
        sibling_idx = idx ^ 1
        proof.append("0x" + level[sibling_idx].to_bytes(32, "big").hex())
        idx >>= 1
    return proof


# ---------------------------------------------------------------------------
# Web3 helpers
# ---------------------------------------------------------------------------
def build_web3() -> Web3:
    w3 = Web3(HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
    try:
        from web3.middleware import ExtraDataToPOAMiddleware

        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except ImportError:
        pass
    return w3


def send_tx(w3: Web3, private_key: str, tx_func, *, label: str = "tx") -> dict:
    account = Account.from_key(private_key)
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    est = tx_func.estimate_gas({"from": account.address})
    tx = tx_func.build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "gas": int(est * 1.3),
            "gasPrice": w3.eth.gas_price,
            "chainId": CHAIN_ID,
        }
    )
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = w3.eth.send_raw_transaction(raw)
    print(f"  [{label}] tx: 0x{tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(f"[{label}] REVERTED! tx=0x{tx_hash.hex()}")
    print(f"  [{label}] mined block={receipt['blockNumber']} gas={receipt['gasUsed']}")
    return dict(receipt)


def sign_commit_auth(market_address, market_id, ticket_id, commitment, user_address, nonce, expiry, ticket_value_wei):
    digest = Web3.solidity_keccak(
        ["address", "uint256", "uint256", "bytes32", "address", "uint256", "uint256", "uint256", "uint256"],
        [
            Web3.to_checksum_address(market_address),
            market_id,
            ticket_id,
            commitment,
            Web3.to_checksum_address(user_address),
            nonce,
            expiry,
            ticket_value_wei,
            CHAIN_ID,
        ],
    )
    signed = Account.sign_message(encode_defunct(hexstr=digest.hex()), AUTH_SIGNER_KEY)
    return signed.signature


# ---------------------------------------------------------------------------
# DB helpers (psycopg2, sync — used for manual inserts)
# ---------------------------------------------------------------------------
def get_db_conn():
    import psycopg2

    # Strip SQLAlchemy dialect prefix if present
    url = DB_URL
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix) :]
            break
    return psycopg2.connect(url)


def db_execute(sql, params=None, fetch=False):
    conn = get_db_conn()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql, params)
    result = cur.fetchall() if fetch else None
    cur.close()
    conn.close()
    return result


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    w3 = build_web3()
    print(f"Connected to chain {w3.eth.chain_id}, block {w3.eth.block_number}")
    print(f"Block timestamp: {w3.eth.get_block('latest')['timestamp']}, local: {int(time.time())}")

    factory = w3.eth.contract(address=w3.to_checksum_address(FACTORY), abi=FACTORY_ABI)
    escrow = w3.eth.contract(address=w3.to_checksum_address(RELAYER_ESCROW), abi=ESCROW_ABI)
    rake_bps = factory.functions.globalRakeBps().call()
    print(f"Factory rake: {rake_bps} bps")

    user_escrow = escrow.functions.balanceOf(w3.to_checksum_address(USER_ADDRESS)).call()
    print(f"User escrow balance: {user_escrow / 1e18:.4f} ZEN")
    if user_escrow < 2 * TICKET_SIZE:
        print("ERROR: User needs at least 2 ZEN in escrow!")
        return 1

    # =====================================================================
    # PHASE 1: Create Market On-Chain
    # =====================================================================
    print("\n" + "=" * 60)
    print("  PHASE 1: Create Market On-Chain")
    print("=" * 60)

    # Check if we should resume from an existing market (e.g., previous run created it)
    resume_market_id = int(os.environ.get("RESUME_MARKET_ID", "0"))
    if resume_market_id > 0:
        market_id = resume_market_id
        market_address = factory.functions.marketAddress(market_id).call()
        print(f"  RESUMING existing market ID={market_id} at {market_address}")
    else:
        commit_deadline = int(time.time()) + COMMIT_DEADLINE_SECS
        circuit_hash_bytes = bytes.fromhex(CIRCUIT_HASH[2:])

        create_params = (
            w3.to_checksum_address(ORACLE_ADDRESS),
            w3.to_checksum_address(VERIFIER),
            circuit_hash_bytes,
            commit_deadline,
            TICKET_SIZE,
            MAX_COMMITMENTS,
            w3.to_checksum_address(AUTH_SIGNER_ADDRESS),
            LIABILITY_CAP,
        )

        print(f"  commitDeadline: {commit_deadline} (in {COMMIT_DEADLINE_SECS}s)")
        print(f"  ticketSize: {TICKET_SIZE / 1e18} ZEN")
        print(f"  liabilityCap: {LIABILITY_CAP / 1e18} ZEN")

        send_tx(w3, DEPLOYER_KEY, factory.functions.createMarket(create_params), label="createMarket")

        next_id = factory.functions.nextMarketId().call()
        market_id = next_id - 1
        market_address = factory.functions.marketAddress(market_id).call()

    print(f"  Market ID: {market_id}")
    print(f"  Market address: {market_address}")

    market_contract = w3.eth.contract(address=w3.to_checksum_address(market_address), abi=MARKET_ABI)
    on_rake = market_contract.functions.rakeBps().call()
    print(f"  On-chain rake: {on_rake} bps")

    # Read commit_deadline from chain (needed for both new and resumed markets)
    commit_deadline = market_contract.functions.commitDeadline().call()
    print(f"  commitDeadline (on-chain): {commit_deadline}")

    # Verify phase
    phase = market_contract.functions.phase().call()
    print(f"  Phase: {phase} (0=Commit)")
    if phase != 0:
        print(f"  WARNING: Market is not in Commit phase! Phase={phase}")
        if market_contract.functions.nextTicketId().call() > 0:
            print("  Tickets already committed — skipping to monitoring.")
            # Could skip to monitoring phase
    assert phase == 0, f"Phase should be Commit (0), got {phase}"

    # =====================================================================
    # PHASE 2: Register Market in DB
    # =====================================================================
    print("\n" + "=" * 60)
    print("  PHASE 2: Register Market in DB")
    print("=" * 60)

    closes_at = datetime.fromtimestamp(commit_deadline, tz=UTC)
    event_id = f"e2e-prod-{market_id}-{int(time.time())}"
    condition_id = f"0x{hashlib.sha256(event_id.encode()).hexdigest()[:64]}"

    # Insert market
    db_execute(
        """
        INSERT INTO markets (event_id, title, category, oracle, factory, onchain_market_id,
                            market_address, status, closes_at, condition_id, rake_bps,
                            resolution_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """,
        (
            event_id,
            f"E2E Prod Test: Market #{market_id}",
            "test",
            ORACLE_ADDRESS.lower(),
            FACTORY.lower(),
            market_id,
            market_address.lower(),
            "commit",
            closes_at,
            condition_id,
            on_rake,
            "final",  # Mark as final so worker knows it's resolved
        ),
    )
    print(f"  Inserted market: event_id={event_id}")

    # Get the DB market ID
    rows = db_execute("SELECT id FROM markets WHERE event_id = %s", (event_id,), fetch=True)
    db_market_id = rows[0][0]
    print(f"  DB market ID: {db_market_id}")

    # Insert market outcomes
    db_execute(
        """
        INSERT INTO market_outcomes (market_id, outcome_id, label, price) VALUES (%s, 0, 'Yes', 0.5)
    """,
        (db_market_id,),
    )
    db_execute(
        """
        INSERT INTO market_outcomes (market_id, outcome_id, label, price) VALUES (%s, 1, 'No', 0.5)
    """,
        (db_market_id,),
    )
    print("  Inserted market_outcomes (Yes/No)")

    # Insert resolution (YES wins, outcome 0)
    winning_outcome = 0
    db_execute(
        """
        INSERT INTO resolutions (condition_id, market_id, event_id, source, resolved, payouts,
                                winning_outcome_id, rake_bps, checked_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """,
        (
            condition_id,
            db_market_id,
            event_id,
            "e2e_test",
            True,
            json.dumps([1, 0]),  # YES wins
            winning_outcome,
            on_rake,
            datetime.now(tz=UTC),
        ),
    )
    print(f"  Inserted resolution: winning_outcome={winning_outcome} (YES)")

    # =====================================================================
    # PHASE 3: Commit YES and NO
    # =====================================================================
    print("\n" + "=" * 60)
    print("  PHASE 3: Commit YES (outcome 0) and NO (outcome 1)")
    print("=" * 60)

    net_amount = TICKET_SIZE - (TICKET_SIZE * on_rake // 10000)
    # payout = total escrow from both tickets * (10000 - rake) / 10000 for the winner
    # With 2 tickets at 1 ZEN each, total = 2 ZEN, net per ticket = 0.98 ZEN
    # Winner payout = 2 * net_amount = 1.96 ZEN
    payout = 2 * net_amount
    print(f"  Net amount per ticket: {net_amount / 1e18:.4f} ZEN")
    print(f"  Winner payout: {payout / 1e18:.4f} ZEN")

    user_int = address_to_field(USER_ADDRESS)
    tickets = []

    for outcome_id in [0, 1]:
        ticket_id = outcome_id  # 0 for YES, 1 for NO
        salt_int = secrets.randbelow(FIELD_MODULUS)
        salt_hex = "0x" + salt_int.to_bytes(32, "big").hex()

        leaf_int = compute_leaf(ticket_id, outcome_id, net_amount, payout, user_int, salt_int)
        leaf_hex = "0x" + leaf_int.to_bytes(32, "big").hex()
        commitment_bytes = leaf_int.to_bytes(32, "big")

        print(f"\n  Ticket {ticket_id} (outcome={outcome_id}, {'YES' if outcome_id == 0 else 'NO'}):")
        print(f"    salt: {salt_hex[:18]}...")
        print(f"    leaf: {leaf_hex[:18]}...")

        # Sign CommitAuth
        nonce = secrets.randbits(256)
        expiry = int(time.time()) + 600
        signature = sign_commit_auth(
            market_address,
            market_id,
            ticket_id,
            commitment_bytes,
            USER_ADDRESS,
            nonce,
            expiry,
            TICKET_SIZE,
        )

        # Call commitOnBehalf via relayer (escrow owner)
        auth_tuple = (commitment_bytes, ticket_id, w3.to_checksum_address(USER_ADDRESS), nonce, expiry, TICKET_SIZE)
        send_tx(
            w3,
            RELAYER_KEY,
            escrow.functions.commitOnBehalf(
                w3.to_checksum_address(USER_ADDRESS),
                w3.to_checksum_address(market_address),
                auth_tuple,
                signature,
            ),
            label=f"commit-{'YES' if outcome_id == 0 else 'NO'}",
        )

        # Verify on-chain
        stored = market_contract.functions.commitmentAt(ticket_id).call()
        assert stored == commitment_bytes, f"On-chain commitment mismatch for ticket {ticket_id}"
        print("    On-chain commitment verified ✓")

        tickets.append(
            {
                "ticket_id": ticket_id,
                "outcome_id": outcome_id,
                "amount": net_amount,
                "payout": payout,
                "salt_int": salt_int,
                "salt_hex": salt_hex,
                "leaf_int": leaf_int,
                "leaf_hex": leaf_hex,
                "user_int": user_int,
            }
        )

        # Insert commitment in DB
        db_execute(
            """
            INSERT INTO commitments (market_id, user_address, outcome_id, amount_wei, payout_wei,
                                    salt, ticket_hash, leaf, leaf_index)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                db_market_id,
                USER_ADDRESS.lower(),
                outcome_id,
                net_amount,
                payout,
                salt_hex,
                leaf_hex,  # ticket_hash = leaf for simplicity
                leaf_hex,
                ticket_id,
            ),
        )
        print("    DB commitment inserted ✓")

    # =====================================================================
    # PHASE 4: Build Merkle Tree & Store Proofs
    # =====================================================================
    print("\n" + "=" * 60)
    print("  PHASE 4: Build Merkle Tree & Store Merkle Proofs")
    print("=" * 60)

    leaves = [t["leaf_int"] for t in tickets]
    tree = build_merkle_tree(leaves)
    batch_root = tree[-1][0]
    batch_root_hex = "0x" + batch_root.to_bytes(32, "big").hex()
    print(f"  Batch root: {batch_root_hex[:18]}...")
    print(f"  Ticket count: {len(tickets)}")

    # Extract and store merkle proofs for each ticket
    merkle_proofs = {}
    for t in tickets:
        proof = extract_merkle_proof(tree, t["ticket_id"])
        merkle_proofs[t["ticket_id"]] = proof
        print(f"  Merkle proof for ticket {t['ticket_id']}: {len(proof)} siblings")

        # Get commitment DB id
        rows = db_execute(
            "SELECT id FROM commitments WHERE market_id = %s AND leaf_index = %s",
            (db_market_id, t["ticket_id"]),
            fetch=True,
        )
        commitment_db_id = rows[0][0]

        # Insert merkle path entries
        for level, sibling_hash in enumerate(proof):
            db_execute(
                """
                INSERT INTO commitment_merkle_paths (commitment_id, level, sibling_hash)
                VALUES (%s, %s, %s)
            """,
                (commitment_db_id, level, sibling_hash),
            )
        print(f"    Stored {len(proof)} merkle path entries in DB ✓")

    # =====================================================================
    # PHASE 5: Wait for Commit Deadline
    # =====================================================================
    print("\n" + "=" * 60)
    print("  PHASE 5: Wait for Commit Deadline")
    print("=" * 60)

    now = int(time.time())
    wait = commit_deadline - now + 5  # 5s buffer
    if wait > 0:
        print(f"  Waiting {wait}s for commit deadline...")
        time.sleep(wait)
    print("  Deadline passed!")

    # Verify on-chain state
    phase = market_contract.functions.phase().call()
    next_ticket = market_contract.functions.nextTicketId().call()
    total_escrow = market_contract.functions.totalEscrow().call()
    print(f"  Phase: {phase} (should be 0 = Commit)")
    print(f"  Next ticket ID: {next_ticket}")
    print(f"  Total escrow: {total_escrow / 1e18:.4f} ZEN")

    # =====================================================================
    # PHASE 6: Save State & Monitor Worker
    # =====================================================================
    print("\n" + "=" * 60)
    print("  PHASE 6: State Summary")
    print("=" * 60)

    state = {
        "market_address": market_address,
        "market_id": market_id,
        "db_market_id": db_market_id,
        "event_id": event_id,
        "condition_id": condition_id,
        "commit_deadline": commit_deadline,
        "closes_at": closes_at.isoformat(),
        "winning_outcome": winning_outcome,
        "rake_bps": on_rake,
        "batch_root": batch_root_hex,
        "tickets": [
            {
                "ticket_id": t["ticket_id"],
                "outcome_id": t["outcome_id"],
                "amount": str(t["amount"]),
                "payout": str(t["payout"]),
                "salt": t["salt_hex"],
                "leaf": t["leaf_hex"],
            }
            for t in tickets
        ],
        "merkle_proofs": {str(k): v for k, v in merkle_proofs.items()},
    }

    state_file = os.path.join(SCRIPTS_DIR, "prod_e2e_state.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  State saved to {state_file}")
    print(f"\n  Market address: {market_address}")
    print(f"  Market ID (on-chain): {market_id}")
    print(f"  Market ID (DB): {db_market_id}")
    print(f"  Event ID: {event_id}")
    print(f"  Winning outcome: {winning_outcome} (YES)")
    print(f"  Batch root: {batch_root_hex[:18]}...")
    print("\n  The worker should now pick up this market and:")
    print("    1. lockBatches (phase 0→1)")
    print(f"    2. postResult (winning_outcome={winning_outcome})")
    print("    3. Generate proof via prover")
    print("    4. verifyAndSettle (phase 1→2)")
    print("\n  Monitor worker logs with:")
    print(f"    docker compose logs -f worker | grep -iE '{event_id[:20]}|lock_batch|post_result|proof|settle'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
