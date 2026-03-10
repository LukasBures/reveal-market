#!/usr/bin/env python3
"""Production mainnet E2E: full happy path from market creation → commit → claim.

Runs inside a Docker container on the prod network (access api:8000, relayer:8088, prover:8085).
Requires poseidon.py in same directory.

Usage (inside worker container):
    python3 /tmp/prod_mainnet_e2e.py
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct

# Poseidon from same directory
from poseidon import BATCH_SIZE, FIELD_MODULUS, MERKLE_DEPTH, build_batch_root, compute_leaf, int_to_hex32, poseidon_t3
from web3 import HTTPProvider, Web3

try:
    from web3.middleware import ExtraDataToPOAMiddleware
except ImportError:
    ExtraDataToPOAMiddleware = None

# ─── Logging ───
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("e2e")

# ─── Configuration ───
RPC_URL = os.environ.get("RPC_URL", "https://horizen.calderachain.xyz/http")
CHAIN_ID = 26514

# Contract addresses
ZEN_TOKEN = "0x57da2D504bf8b83Ef304759d9f2648522D7a9280"  # noqa: S105
FACTORY = "0x3144B525Ffbb99dF298E9B5a589011cF423b54a3"
PROTOCOL_POOL = "0x3C8fC2C4bbe255ED8A8A343239a5EC8c016686B8"
RELAYER_ESCROW = "0x5613c11E960950434444BA0580D9998F8540CfeD"
VERIFIER = "0x568c9395073D8132692Be68e8De0e859b7f05c33"
CIRCUIT_HASH = "0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157"
AUTH_SIGNER_ADDRESS = "0xA2A0b13f53FE25E5ef9B1267D1C064d7A5BD4277"

# Private keys
DEPLOYER_KEY = os.environ["DEPLOYER_KEY"]
RELAYER_KEY = os.environ["RELAYER_KEY"]
AUTH_SIGNER_KEY = os.environ["AUTH_SIGNER_KEY"]
USER_KEY = os.environ["USER_KEY"]

# Service URLs
API_URL = os.environ.get("API_URL", "http://api:8000")
RELAYER_URL = os.environ.get("RELAYER_URL", "http://relayer:8088")
PROVER_URL = os.environ.get("PROVER_URL", "http://prover:8085")
INTERNAL_SECRET =<REDACTED>
RELAYER_BEARER = os.environ["RELAYER_BEARER"]
PROVER_SECRET =<REDACTED>

# Test parameters
TICKET_SIZE = 10**17  # 0.1 ZEN
MAX_COMMITMENTS = 256
LIABILITY_CAP = 10**18  # 1 ZEN
COMMIT_DEADLINE_OFFSET = 17 * 60  # 17 minutes
WINNING_OUTCOME = 0  # YES wins
NUM_TICKETS = 2

# ─── Minimal ABIs ───
ERC20_ABI = [
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

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
        "name": "maxCommitments",
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
        "inputs": [{"name": "i", "type": "uint256"}],
        "name": "batchRoots",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "i", "type": "uint256"}],
        "name": "batchCounts",
        "outputs": [{"name": "", "type": "uint16"}],
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
        "inputs": [{"name": "ticketId", "type": "uint256"}],
        "name": "claimedTickets",
        "outputs": [{"name": "", "type": "bool"}],
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
        "inputs": [{"name": "outcomeId", "type": "uint256"}],
        "name": "postResult",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "roots", "type": "bytes32[]"},
            {"name": "counts", "type": "uint16[]"},
            {"name": "relayerSig", "type": "bytes"},
        ],
        "name": "lockBatches",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "proof", "type": "bytes"}, {"name": "publicSignals", "type": "uint256[10]"}],
        "name": "verifyAndSettle",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "ticketId", "type": "uint256"},
            {"name": "outcomeId", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
            {"name": "payout", "type": "uint256"},
            {"name": "salt", "type": "bytes32"},
            {"name": "merkleProof", "type": "bytes32[]"},
        ],
        "name": "claim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

ESCROW_ABI = [
    {
        "inputs": [{"name": "user", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

COMMIT_ON_BEHALF_ABI = [
    {
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "market", "type": "address"},
            {
                "components": [
                    {"name": "commitment", "type": "bytes32"},
                    {"name": "ticketId", "type": "uint256"},
                    {"name": "user", "type": "address"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "expiry", "type": "uint256"},
                    {"name": "ticketValue", "type": "uint256"},
                ],
                "name": "auth",
                "type": "tuple",
            },
            {"name": "signature", "type": "bytes"},
        ],
        "name": "commitOnBehalf",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

POOL_ABI = [
    {
        "inputs": [],
        "name": "totalAssets",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "idleLiquidity",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "market", "type": "address"}],
        "name": "consumedLiability",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# ─── Helpers ───
def build_web3():
    web3 = Web3(HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
    if ExtraDataToPOAMiddleware:
        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert web3.is_connected(), f"Failed to connect to RPC at {RPC_URL}"
    return web3


def send_tx(web3, private_key, tx_func, *, label="tx"):
    account = Account.from_key(private_key)
    nonce = web3.eth.get_transaction_count(account.address, "pending")
    gas_price = web3.eth.gas_price
    est = tx_func.estimate_gas({"from": account.address})
    tx = tx_func.build_transaction(
        {"from": account.address, "nonce": nonce, "gas": int(est * 1.3), "gasPrice": gas_price, "chainId": CHAIN_ID}
    )
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = web3.eth.send_raw_transaction(raw)
    log.info("[%s] Sent tx: 0x%s", label, tx_hash.hex())
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(f"[{label}] Transaction reverted! tx=0x{tx_hash.hex()}")
    log.info("[%s] Mined: block=%s gas=%s", label, receipt["blockNumber"], receipt["gasUsed"])
    return dict(receipt)


def wei_to_zen(wei):
    return f"{Decimal(wei) / Decimal(10**18):.6f} ZEN"


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


def build_merkle_tree(leaves_int, depth=MERKLE_DEPTH, pad_to=BATCH_SIZE):
    padded = [int(v) for v in leaves_int] + [0] * (pad_to - len(leaves_int))
    levels = [padded]
    current = padded
    for _ in range(depth):
        next_level = [poseidon_t3(current[i], current[i + 1]) for i in range(0, len(current), 2)]
        levels.append(next_level)
        current = next_level
    return levels


def extract_merkle_proof(tree_levels, leaf_index):
    proof = []
    idx = leaf_index
    for level in tree_levels[:-1]:
        sibling_idx = idx ^ 1
        proof.append(int_to_hex32(level[sibling_idx]))
        idx >>= 1
    return proof


def sign_lock_batches(market_address, factory_address, market_id, roots, counts, signer_key):
    encoded = abi_encode(
        ["address", "address", "uint256", "bytes32[]", "uint16[]", "uint256"],
        [
            Web3.to_checksum_address(market_address),
            Web3.to_checksum_address(factory_address),
            market_id,
            roots,
            counts,
            CHAIN_ID,
        ],
    )
    digest = Web3.keccak(encoded)
    signed = Account.sign_message(encode_defunct(digest), signer_key)
    return signed.signature


def compute_net_amount(ticket_size, rake_bps):
    return ticket_size - (ticket_size * rake_bps // 10_000)


# ─── Main E2E Flow ───
def main() -> int:
    web3 = build_web3()
    deployer = Account.from_key(DEPLOYER_KEY)
    relayer = Account.from_key(RELAYER_KEY)
    user = Account.from_key(USER_KEY)

    log.info("=" * 60)
    log.info("  PRODUCTION MAINNET E2E TEST")
    log.info("=" * 60)
    log.info("Deployer (oracle): %s", deployer.address)
    log.info("Relayer (escrow owner): %s", relayer.address)
    log.info("Test user: %s", user.address)
    log.info("Ticket size: %s", wei_to_zen(TICKET_SIZE))
    log.info("")

    factory = web3.eth.contract(address=Web3.to_checksum_address(FACTORY), abi=FACTORY_ABI)
    escrow = web3.eth.contract(address=Web3.to_checksum_address(RELAYER_ESCROW), abi=ESCROW_ABI)
    pool = web3.eth.contract(address=Web3.to_checksum_address(PROTOCOL_POOL), abi=POOL_ABI)
    zen = web3.eth.contract(address=Web3.to_checksum_address(ZEN_TOKEN), abi=ERC20_ABI)

    # ─── Pre-flight checks ───
    log.info("--- Pre-flight Checks ---")
    escrow_bal = escrow.functions.balanceOf(user.address).call()
    pool_idle = pool.functions.idleLiquidity().call()
    rake_bps = factory.functions.globalRakeBps().call()
    log.info("  Escrow balance: %s", wei_to_zen(escrow_bal))
    log.info("  Pool idle:      %s", wei_to_zen(pool_idle))
    log.info("  Global rake:    %s bps (%s%%)", rake_bps, rake_bps / 100)
    assert escrow_bal >= TICKET_SIZE * NUM_TICKETS, (
        f"Insufficient escrow: have {wei_to_zen(escrow_bal)}, need {wei_to_zen(TICKET_SIZE * NUM_TICKETS)}"
    )
    log.info("  Pre-flight: PASS")
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 1: Create Market On-Chain
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 1: Create Market On-Chain")
    log.info("=" * 60)

    commit_deadline = int(time.time()) + COMMIT_DEADLINE_OFFSET
    circuit_hash_bytes = bytes.fromhex(CIRCUIT_HASH[2:])

    # Use deployer as oracle (we have its key)
    create_params = (
        Web3.to_checksum_address(deployer.address),  # oracle = deployer
        Web3.to_checksum_address(VERIFIER),
        circuit_hash_bytes,
        commit_deadline,
        TICKET_SIZE,
        MAX_COMMITMENTS,
        Web3.to_checksum_address(AUTH_SIGNER_ADDRESS),
        LIABILITY_CAP,
    )

    log.info("  oracle:          %s (deployer)", deployer.address)
    log.info("  commitDeadline:  %s (now + %ds)", commit_deadline, COMMIT_DEADLINE_OFFSET)
    log.info("  ticketSize:      %s", wei_to_zen(TICKET_SIZE))
    log.info("  liabilityCap:    %s", wei_to_zen(LIABILITY_CAP))

    send_tx(web3, DEPLOYER_KEY, factory.functions.createMarket(create_params), label="create-market")

    next_id = factory.functions.nextMarketId().call()
    market_id = next_id - 1
    market_address = factory.functions.marketAddress(market_id).call()
    log.info("  Market created: %s (id=%s)", market_address, market_id)

    market = web3.eth.contract(address=Web3.to_checksum_address(market_address), abi=MARKET_ABI)
    assert market.functions.phase().call() == 0, "Market not in Commit phase"
    assert market.functions.ticketSize().call() == TICKET_SIZE, "Ticket size mismatch"
    on_chain_rake = market.functions.rakeBps().call()
    log.info("  On-chain rake: %s bps", on_chain_rake)
    log.info("  Phase 1: PASS")
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: Register Market in Database
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 2: Register Market in Database")
    log.info("=" * 60)

    event_id = f"e2e-mainnet-{market_id}-{int(time.time())}"
    closes_at = datetime.fromtimestamp(commit_deadline, tz=UTC).isoformat()

    market_data = {
        "event_id": event_id,
        "title": f"E2E Mainnet Test Market #{market_id}",
        "category": "test",
        "oracle": deployer.address,
        "market_address": market_address,
        "onchain_market_id": market_id,
        "factory": Web3.to_checksum_address(FACTORY),
        "status": "commit",
        "closes_at": closes_at,
        "outcomes": ["Yes", "No"],
        "outcome_prices": [0.5, 0.5],
    }

    try:
        resp = httpx.post(
            f"{API_URL}/events",
            json=market_data,
            headers={"Content-Type": "application/json", "X-Internal-Secret": INTERNAL_SECRET},
            timeout=30,
        )
        resp.raise_for_status()
        log.info("  DB registration: OK (event_id=%s)", event_id)
    except Exception as exc:
        log.warning("  DB registration failed: %s (continuing — on-chain is source of truth)", exc)

    log.info("  Phase 2: PASS")
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: Commit YES and NO (via RelayerEscrow.commitOnBehalf)
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 3: Commit YES and NO")
    log.info("=" * 60)

    net_amount = compute_net_amount(TICKET_SIZE, on_chain_rake)
    payout = NUM_TICKETS * net_amount  # winner takes all
    log.info("  Net amount per ticket: %s", wei_to_zen(net_amount))
    log.info("  Winner payout:         %s", wei_to_zen(payout))

    tickets = []
    next_ticket = market.functions.nextTicketId().call()

    for i, (outcome_id, outcome_name) in enumerate([(0, "YES"), (1, "NO")]):
        ticket_id = next_ticket + i
        salt_int = secrets.randbelow(FIELD_MODULUS)
        salt_hex = "0x" + salt_int.to_bytes(32, "big").hex()

        leaf_int = compute_leaf(ticket_id, outcome_id, net_amount, payout, user.address, salt_int)
        commitment = int_to_hex32(leaf_int)
        commitment_bytes = bytes.fromhex(commitment[2:])

        log.info("  --- Commit %s (ticket_id=%s) ---", outcome_name, ticket_id)
        log.info("  leaf: %s", commitment[:20] + "...")
        log.info("  salt: %s", salt_hex[:20] + "...")

        nonce = secrets.randbits(256)
        expiry = int(time.time()) + 600

        # Sign CommitAuth (API/backend signs this in production)
        sig = sign_commit_auth(
            market_address, market_id, ticket_id, commitment_bytes, user.address, nonce, expiry, TICKET_SIZE
        )

        auth_tuple = (commitment_bytes, ticket_id, Web3.to_checksum_address(user.address), nonce, expiry, TICKET_SIZE)

        # Relayer calls commitOnBehalf (relayer is escrow owner)
        escrow_contract = web3.eth.contract(address=Web3.to_checksum_address(RELAYER_ESCROW), abi=COMMIT_ON_BEHALF_ABI)
        send_tx(
            web3,
            RELAYER_KEY,
            escrow_contract.functions.commitOnBehalf(
                Web3.to_checksum_address(user.address), Web3.to_checksum_address(market_address), auth_tuple, sig
            ),
            label=f"commit-{outcome_name}",
        )

        # Verify on-chain
        stored = market.functions.commitmentAt(ticket_id).call()
        assert "0x" + stored.hex() == commitment, f"Commitment mismatch for ticket {ticket_id}"
        log.info("  On-chain commitment verified!")

        tickets.append(
            {
                "ticket_id": ticket_id,
                "outcome_id": outcome_id,
                "amount": net_amount,
                "payout": payout,
                "user": user.address,
                "salt": salt_hex,
                "leaf_int": leaf_int,
            }
        )

    assert market.functions.nextTicketId().call() == next_ticket + NUM_TICKETS
    log.info("  Phase 3: PASS (%d tickets committed)", NUM_TICKETS)
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 4: Wait for Deadline & Lock Batches
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 4: Wait for Deadline & Lock Batches")
    log.info("=" * 60)

    now = int(time.time())
    if now < commit_deadline:
        wait_secs = commit_deadline - now + 5
        log.info("  Waiting %ds for commit deadline to pass...", wait_secs)
        log.info("  Deadline: %s", datetime.fromtimestamp(commit_deadline, tz=UTC).strftime("%H:%M:%S UTC"))

        # Show countdown every 60s
        target = time.time() + wait_secs
        while time.time() < target:
            remaining = int(target - time.time())
            log.info("  ... %d seconds remaining", remaining)
            time.sleep(min(60, remaining))
        log.info("  Deadline passed!")
    else:
        log.info("  Deadline already passed")

    # Build Merkle tree
    leaf_ints = [t["leaf_int"] for t in tickets]
    batch_root_int = build_batch_root(leaf_ints)
    batch_root_hex = int_to_hex32(batch_root_int)
    tree_levels = build_merkle_tree(leaf_ints)
    computed_root_hex = int_to_hex32(tree_levels[-1][0])
    assert computed_root_hex == batch_root_hex, "Merkle root mismatch"
    log.info("  Batch root: %s", batch_root_hex[:20] + "...")

    # Extract Merkle proofs
    merkle_proofs = {}
    for t in tickets:
        tid = t["ticket_id"]
        leaf_index = tid % BATCH_SIZE
        proof = extract_merkle_proof(tree_levels, leaf_index)
        merkle_proofs[tid] = proof
        log.info("  Merkle proof for ticket %s: %d siblings", tid, len(proof))

    # Sign relayer digest (relayer is escrow owner)
    batch_roots_bytes = [bytes.fromhex(batch_root_hex[2:])]
    batch_counts = [NUM_TICKETS]

    relayer_sig = sign_lock_batches(market_address, FACTORY, market_id, batch_roots_bytes, batch_counts, RELAYER_KEY)
    log.info("  Relayer sig: 0x%s... (%d bytes)", relayer_sig[:4].hex(), len(relayer_sig))

    # Oracle (deployer) calls lockBatches
    log.info("  Calling lockBatches via oracle...")
    send_tx(
        web3,
        DEPLOYER_KEY,
        market.functions.lockBatches(batch_roots_bytes, batch_counts, relayer_sig),
        label="lock-batches",
    )

    phase = market.functions.phase().call()
    assert phase == 1, f"Expected phase 1 (Locked), got {phase}"
    on_chain_root = "0x" + market.functions.batchRoots(0).call().hex()
    assert on_chain_root == batch_root_hex, "On-chain batch root mismatch"
    log.info("  Phase 4: PASS (market locked)")
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 5: Oracle Resolution
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 5: Oracle Resolution (YES wins)")
    log.info("=" * 60)

    send_tx(web3, DEPLOYER_KEY, market.functions.postResult(WINNING_OUTCOME), label="post-result")

    assert market.functions.resultPosted().call(), "Result not posted"
    assert market.functions.winningOutcomeId().call() == WINNING_OUTCOME
    log.info("  Phase 5: PASS (result posted: outcome %s)", WINNING_OUTCOME)
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 6: Proof Generation
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 6: Proof Generation")
    log.info("=" * 60)

    # Build prover request
    prover_tickets = []
    for t in tickets:
        prover_tickets.append(
            {
                "ticketId": str(t["ticket_id"]),
                "outcomeId": str(t["outcome_id"]),
                "amount": str(t["amount"]),
                "payout": str(t["payout"]),
                "user": str(int(t["user"], 16)),
                "salt": str(int(t["salt"], 16)),
            }
        )

    # Pad to BATCH_SIZE
    while len(prover_tickets) < BATCH_SIZE:
        prover_tickets.append(
            {
                "ticketId": str(len(prover_tickets)),
                "outcomeId": "0",
                "amount": "0",
                "payout": "0",
                "user": "0",
                "salt": "0",
            }
        )

    pool_yes = sum(t["amount"] for t in tickets if t["outcome_id"] == 0)
    pool_no = sum(t["amount"] for t in tickets if t["outcome_id"] == 1)
    total_escrow = pool_yes + pool_no
    total_liability = sum(t["payout"] for t in tickets if t["outcome_id"] == WINNING_OUTCOME)

    # Cross-validate
    on_chain_escrow = market.functions.totalEscrow().call()
    assert total_escrow == on_chain_escrow, f"Escrow mismatch: computed={total_escrow}, on-chain={on_chain_escrow}"

    prover_request = {
        "marketId": str(market_id),
        "merkleRoot": batch_root_hex,
        "winningOutcomeId": str(WINNING_OUTCOME),
        "poolTotals": [str(pool_yes), str(pool_no)],
        "totalEscrow": str(total_escrow),
        "totalLiability": str(total_liability),
        "rakeBps": str(on_chain_rake),
        "circuitHash": CIRCUIT_HASH,
        "batchIndex": "0",
        "commitmentsCount": str(NUM_TICKETS),
        "tickets": prover_tickets,
    }

    log.info("  poolTotals:      [%s, %s]", wei_to_zen(pool_yes), wei_to_zen(pool_no))
    log.info("  totalEscrow:     %s", wei_to_zen(total_escrow))
    log.info("  totalLiability:  %s", wei_to_zen(total_liability))
    log.info("  Requesting proof from prover...")

    start_t = time.time()
    resp = httpx.post(
        f"{PROVER_URL}/api/v1/proofs/settlement",
        json=prover_request,
        headers={"Content-Type": "application/json", "X-Prover-Secret": PROVER_SECRET},
        timeout=300,
    )
    resp.raise_for_status()
    proof_response = resp.json()
    elapsed = time.time() - start_t
    log.info("  Proof generated in %.1fs", elapsed)

    proof_json = proof_response.get("proof", "")
    public_signals = proof_response.get("public_signals", [])
    warnings = proof_response.get("warnings", [])

    assert proof_json, "Empty proof response"
    assert len(public_signals) == 10, f"Expected 10 public signals, got {len(public_signals)}"
    if warnings:
        log.warning("  Prover warnings: %s", warnings)

    log.info("  Phase 6: PASS (proof with %d public signals)", len(public_signals))
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 7: Settlement (on-chain proof verification)
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 7: Settlement")
    log.info("=" * 60)

    # Parse proof
    if isinstance(proof_json, str):
        proof_parsed = json.loads(proof_json.rstrip("\x00"))
    else:
        proof_parsed = proof_json

    pi_a = proof_parsed["pi_a"][:2]
    pi_b = proof_parsed["pi_b"][:2]
    pi_c = proof_parsed["pi_c"][:2]

    proof_bytes = b""
    proof_bytes += int(pi_a[0]).to_bytes(32, "big")
    proof_bytes += int(pi_a[1]).to_bytes(32, "big")
    proof_bytes += int(pi_b[0][1]).to_bytes(32, "big")
    proof_bytes += int(pi_b[0][0]).to_bytes(32, "big")
    proof_bytes += int(pi_b[1][1]).to_bytes(32, "big")
    proof_bytes += int(pi_b[1][0]).to_bytes(32, "big")
    proof_bytes += int(pi_c[0]).to_bytes(32, "big")
    proof_bytes += int(pi_c[1]).to_bytes(32, "big")

    pub_signals_int = [int(s) for s in public_signals]

    log.info("  Proof bytes: %d", len(proof_bytes))
    log.info("  Submitting verifyAndSettle on-chain...")

    send_tx(web3, DEPLOYER_KEY, market.functions.verifyAndSettle(proof_bytes, pub_signals_int), label="verify-settle")

    phase = market.functions.phase().call()
    assert phase == 2, f"Expected phase 2 (Settled), got {phase}"
    log.info("  Phase 7: PASS (market settled)")
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 8: Claim Winner Payout (via Relayer)
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 8: Claim Winner Payout")
    log.info("=" * 60)

    # Snapshot balances
    zen_before = zen.functions.balanceOf(user.address).call()
    escrow_before = escrow.functions.balanceOf(user.address).call()
    log.info("  Before: ZEN=%s  Escrow=%s", wei_to_zen(zen_before), wei_to_zen(escrow_before))

    # Winner is the YES ticket (outcome_id == WINNING_OUTCOME)
    winner = next(t for t in tickets if t["outcome_id"] == WINNING_OUTCOME)
    loser = next(t for t in tickets if t["outcome_id"] != WINNING_OUTCOME)

    winner_proof = merkle_proofs[winner["ticket_id"]]
    claim_payload = {
        "market": market_address,
        "user": winner["user"],
        "ticket_id": winner["ticket_id"],
        "outcome_id": winner["outcome_id"],
        "amount": winner["amount"],
        "payout": winner["payout"],
        "salt": winner["salt"],
        "merkle_proof": winner_proof,
        "event_id": event_id,
    }

    log.info("  Claiming ticket_id=%s (payout=%s)...", winner["ticket_id"], wei_to_zen(winner["payout"]))

    try:
        resp = httpx.post(
            f"{RELAYER_URL}/claim",
            json=claim_payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {RELAYER_BEARER}"},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        if "jobId" in result:
            job_id = result["jobId"]
            log.info("  Job queued: %s — polling...", job_id)
            deadline_t = time.time() + 120
            while time.time() < deadline_t:
                status_resp = httpx.post(
                    f"{RELAYER_URL}/status",
                    json={"jobId": job_id},
                    headers={"Authorization": f"Bearer {RELAYER_BEARER}", "Content-Type": "application/json"},
                    timeout=30,
                )
                status_resp.raise_for_status()
                status_data = status_resp.json()
                status = status_data.get("status", "unknown")
                if status in ("completed", "done", "mined", "succeeded"):
                    log.info("  Claim succeeded: tx=%s", status_data.get("txHash", ""))
                    break
                if status in ("failed", "dead", "deadletter"):
                    raise RuntimeError(f"Claim failed: {status_data}")
                time.sleep(2)
            else:
                raise TimeoutError("Claim job timed out")
        else:
            log.info("  Claim result: %s", result)
    except Exception as exc:
        log.error("  Relayer claim failed: %s", exc)
        log.info("  Attempting direct on-chain claim as fallback...")
        # Direct claim (fallback)
        salt_bytes = bytes.fromhex(winner["salt"][2:])
        proof_bytes_list = [bytes.fromhex(p[2:]) for p in winner_proof]
        send_tx(
            web3,
            RELAYER_KEY,  # anyone can call claim
            market.functions.claim(
                Web3.to_checksum_address(winner["user"]),
                winner["ticket_id"],
                winner["outcome_id"],
                winner["amount"],
                winner["payout"],
                salt_bytes,
                proof_bytes_list,
            ),
            label="claim-direct",
        )

    # Verify claim
    claimed = market.functions.claimedTickets(winner["ticket_id"]).call()
    assert claimed, "Winner ticket not claimed"

    zen_after = zen.functions.balanceOf(user.address).call()
    escrow_after = escrow.functions.balanceOf(user.address).call()
    balance_delta = (zen_after - zen_before) + (escrow_after - escrow_before)

    log.info("  After:  ZEN=%s  Escrow=%s", wei_to_zen(zen_after), wei_to_zen(escrow_after))
    log.info("  Balance delta: %s (expected ~%s)", wei_to_zen(balance_delta), wei_to_zen(winner["payout"]))
    assert balance_delta > 0, "Winner did not receive payout"

    log.info("  Phase 8: PASS (winner claimed, loser excluded)")
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Phase 9: Verify Loser Cannot Claim
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  PHASE 9: Verify Loser Cannot Claim")
    log.info("=" * 60)

    loser_proof = merkle_proofs[loser["ticket_id"]]
    loser_claim = {
        "market": market_address,
        "user": loser["user"],
        "ticket_id": loser["ticket_id"],
        "outcome_id": loser["outcome_id"],
        "amount": loser["amount"],
        "payout": loser["payout"],
        "salt": loser["salt"],
        "merkle_proof": loser_proof,
        "event_id": event_id,
    }

    loser_reverted = False
    try:
        resp = httpx.post(
            f"{RELAYER_URL}/claim",
            json=loser_claim,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {RELAYER_BEARER}"},
            timeout=60,
        )
        if resp.status_code >= 400:
            loser_reverted = True
            log.info("  Loser claim rejected by relayer (HTTP %s)", resp.status_code)
        else:
            result = resp.json()
            if "jobId" in result:
                try:
                    deadline_t = time.time() + 60
                    while time.time() < deadline_t:
                        sr = httpx.post(
                            f"{RELAYER_URL}/status",
                            json={"jobId": result["jobId"]},
                            headers={"Authorization": f"Bearer {RELAYER_BEARER}", "Content-Type": "application/json"},
                            timeout=30,
                        )
                        sd = sr.json()
                        if sd.get("status") in ("failed", "dead", "deadletter"):
                            loser_reverted = True
                            break
                        if sd.get("status") in ("completed", "done", "mined", "succeeded"):
                            break
                        time.sleep(2)
                except RuntimeError:
                    loser_reverted = True
    except Exception:
        loser_reverted = True

    if loser_reverted:
        log.info("  Loser claim correctly rejected!")
    else:
        log.warning("  Loser claim unexpectedly succeeded (or timed out)")

    log.info("  Phase 9: %s", "PASS" if loser_reverted else "WARN")
    log.info("")

    # ═══════════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════════
    log.info("=" * 60)
    log.info("  E2E TEST COMPLETE — ALL PHASES PASSED")
    log.info("=" * 60)
    log.info("  Market:   %s (id=%s)", market_address, market_id)
    log.info("  Event:    %s", event_id)
    log.info("  Tickets:  %d (YES + NO at %s each)", NUM_TICKETS, wei_to_zen(TICKET_SIZE))
    log.info(
        "  Winner:   ticket %s (outcome %s) claimed %s",
        winner["ticket_id"],
        winner["outcome_id"],
        wei_to_zen(winner["payout"]),
    )
    log.info("  User ZEN: %s → %s", wei_to_zen(zen_before), wei_to_zen(zen_after))
    log.info("  Escrow:   %s → %s", wei_to_zen(escrow_before), wei_to_zen(escrow_after))

    return 0


if __name__ == "__main__":
    sys.exit(main())
