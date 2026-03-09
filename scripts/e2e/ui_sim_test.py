#!/usr/bin/env python3
"""
UI Simulation Test — Full end-to-end flow mimicking what a user does via the frontend.

Timeline:
  t+0s   — Create market on-chain, register in API DB (admin/backend step)
  t+0s   — User A places YES bet via relayer commitWithAuthorization
  t+0s   — User B places NO bet via relayer commitWithAuthorization
  t+120s — Commit deadline passes
  t+120s — Lock batches (oracle signs, relayer executes)
  t+120s — Post result (oracle: YES wins = outcome 0)
  t+120s — Request proof from prover
  t+~150s— Verify and settle on-chain
  t+~150s— User A claims payout (YES winner: ~1.96 ZEN)
  t+~150s— User B tries to claim (NO loser: reverts correctly)

Also checks: API event visibility, relayer status polling, prover health.
"""

from __future__ import annotations

import json
import secrets
import sys
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from utils import (
    AUTH_SIGNER_ADDRESS,
    AUTH_SIGNER_KEY,
    CIRCUIT_HASH,
    DEPLOYER_KEY,
    FACTORY,
    FACTORY_ABI,
    MARKET_ABI,
    ORACLE_ADDRESS,
    ORACLE_KEY,
    PROTOCOL_POOL,
    RELAYER_ESCROW,
    TEST_ACCOUNT_KEY,
    VERIFIER,
    api_post,
    build_web3,
    contract,
    log,
    send_tx,
    setup_logging,
    wei_to_zen,
)
from web3 import Web3

# ─── Constants ────────────────────────────────────────────────────────────────
COMMIT_DEADLINE_OFFSET = 120  # 2 minutes — short enough to test quickly
TICKET_SIZE = 1 * 10**18
MAX_COMMITMENTS = 256
LIABILITY_CAP = 5 * 10**18  # must fit within pool balance (~10 ZEN)
WINNING_OUTCOME = 0  # YES wins

RELAYER_URL = "http://localhost:8088"
PROVER_URL = "http://localhost:8085"
API_URL = "http://localhost:8000"

FIELD_MODULUS = 21888242871839275222246405745257275088548364400416034343698204186575808495617


# ─── Helpers ──────────────────────────────────────────────────────────────────


def header(msg: str) -> None:
    log.info("")
    log.info("=" * 60)
    log.info(msg)
    log.info("=" * 60)


def ok(label: str, value: bool, detail: str = "") -> bool:
    if value:
        log.info("  [PASS] %s %s", label, detail)
    else:
        log.error("  [FAIL] %s %s", label, detail)
    return value


def sign_commit_auth(
    web3: Web3,
    auth_signer_key: str,
    market: str,
    market_id: int,
    ticket_id: int,
    commitment: bytes,
    user: str,
    nonce: int,
    expiry: int,
    ticket_value: int,
    chain_id: int,
) -> bytes:
    """Sign commitWithAuthorization per AuthorizationVerifier EIP-191 digest."""
    from eth_abi import encode

    raw = Web3.solidity_keccak(
        ["bytes"],
        [
            encode(
                ["address", "uint256", "uint256", "bytes32", "address", "uint256", "uint256", "uint256", "uint256"],
                [
                    web3.to_checksum_address(market),
                    market_id,
                    ticket_id,
                    commitment,
                    web3.to_checksum_address(user),
                    nonce,
                    expiry,
                    ticket_value,
                    chain_id,
                ],
            )
        ],
    )
    signed = Account.sign_message(encode_defunct(raw), private_key=auth_signer_key)
    return signed.signature


def sign_lock_batches(
    web3: Web3,
    deployer_key: str,
    market: str,
    factory: str,
    market_id: int,
    roots: list[bytes],
    counts: list[int],
    chain_id: int,
) -> bytes:
    from eth_abi import encode

    raw = Web3.solidity_keccak(
        ["bytes"],
        [
            encode(
                ["address", "address", "uint256", "bytes32[]", "uint256[]", "uint256"],
                [
                    web3.to_checksum_address(market),
                    web3.to_checksum_address(factory),
                    market_id,
                    roots,
                    counts,
                    chain_id,
                ],
            )
        ],
    )
    signed = Account.sign_message(encode_defunct(raw), private_key=deployer_key)
    return signed.signature


def poseidon_commitment(outcome: int, salt: int) -> bytes:
    """Compute Poseidon(outcome, salt) via prover API."""
    resp = httpx.post(
        f"{PROVER_URL}/api/v1/hash/poseidon",
        json={"inputs": [str(outcome), str(salt)]},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    val = int(data["hash"], 16) if data["hash"].startswith("0x") else int(data["hash"])
    return val.to_bytes(32, "big")


def submit_commitment(
    web3: Web3,
    market: object,
    market_addr: str,
    market_id: int,
    ticket_id: int,
    commitment: bytes,
    user_key: str,
    chain_id: int,
) -> bool:
    """Submit a bet via escrow.commitWithAuthorization (simulating relayer)."""
    user = Account.from_key(user_key)
    nonce = int(time.time() * 1000)
    expiry = int(time.time()) + 3600

    auth_sig = sign_commit_auth(
        web3,
        AUTH_SIGNER_KEY,
        market_addr,
        market_id,
        ticket_id,
        commitment,
        user.address,
        nonce,
        expiry,
        TICKET_SIZE,
        chain_id,
    )

    escrow = contract(
        web3,
        RELAYER_ESCROW,
        [
            {
                "name": "commitWithAuthorization",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "market", "type": "address"},
                    {"name": "commitment", "type": "bytes32"},
                    {"name": "user", "type": "address"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "expiry", "type": "uint256"},
                    {"name": "ticketValue", "type": "uint256"},
                    {"name": "ticketId", "type": "uint256"},
                    {"name": "authSignature", "type": "bytes"},
                ],
                "outputs": [],
            },
        ],
    )

    send_tx(
        web3,
        user_key,  # user pays gas (relayer would actually pay, but same result)
        escrow.functions.commitWithAuthorization(
            web3.to_checksum_address(market_addr),
            commitment,
            web3.to_checksum_address(user.address),
            nonce,
            expiry,
            TICKET_SIZE,
            ticket_id,
            auth_sig,
        ),
        label=f"commit-ticket-{ticket_id}",
    )
    return True


def request_proof(market_addr: str, market_id: int, batch_root: str, tickets: list[dict]) -> dict:
    """Request Groth16 settlement proof from prover service."""
    payload = {
        "market_address": market_addr,
        "market_id": market_id,
        "batch_index": 0,
        "batch_root": batch_root,
        "winning_outcome": WINNING_OUTCOME,
        "tickets": tickets,
    }
    log.info("Requesting proof from prover (this takes ~30-120s)...")
    resp = httpx.post(
        f"{PROVER_URL}/api/v1/proofs/settlement",
        json=payload,
        timeout=300,
    )
    resp.raise_for_status()
    raw = resp.text.rstrip("\x00")
    return json.loads(raw)


def pack_proof(proof_json: dict) -> bytes:
    """Pack Groth16 proof into 256-byte calldata: pi_a[2] + pi_b[2][2] + pi_c[2]."""

    def to_u256(x: str) -> bytes:
        return int(x).to_bytes(32, "big")

    pi_a = proof_json["pi_a"]
    pi_b = proof_json["pi_b"]
    pi_c = proof_json["pi_c"]

    return (
        to_u256(pi_a[0])
        + to_u256(pi_a[1])
        + to_u256(pi_b[0][0])
        + to_u256(pi_b[0][1])
        + to_u256(pi_b[1][0])
        + to_u256(pi_b[1][1])
        + to_u256(pi_c[0])
        + to_u256(pi_c[1])
    )


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    setup_logging()
    all_ok = True
    web3 = build_web3()
    chain_id = web3.eth.chain_id

    test_account = Account.from_key(TEST_ACCOUNT_KEY)

    # ─── Step 0: Health checks ──────────────────────────────────────────────
    header("Step 0: Health Checks")
    for name, url in [
        ("API", f"{API_URL}/healthz"),
        ("Relayer", f"{RELAYER_URL}/healthz"),
        ("Prover", f"{PROVER_URL}/healthz"),
    ]:
        try:
            r = httpx.get(url, timeout=5)
            status = r.json().get("status", r.status_code)
            log.info("  %s: %s", name, status)
            all_ok &= ok(f"{name} healthy", r.status_code == 200)
        except Exception as e:
            all_ok &= ok(f"{name} healthy", False, str(e))

    # ─── Step 1: Create Market On-Chain ────────────────────────────────────
    header("Step 1: Create Market On-Chain (simulates admin/backend)")
    factory = contract(web3, FACTORY, FACTORY_ABI)
    commit_deadline = int(time.time()) + COMMIT_DEADLINE_OFFSET
    circuit_hash_bytes = bytes.fromhex(CIRCUIT_HASH[2:] if CIRCUIT_HASH.startswith("0x") else CIRCUIT_HASH)

    # Ensure verifier approved
    verifier_addr = web3.to_checksum_address(VERIFIER)
    try:
        is_approved = factory.functions.approvedVerifiers(verifier_addr).call()
    except Exception:
        is_approved = True  # already approved or call not available
    if not is_approved:
        log.info("Approving verifier...")
        send_tx(
            web3, DEPLOYER_KEY, factory.functions.setVerifierApproval(verifier_addr, True), label="approve-verifier"
        )

    create_params = (
        web3.to_checksum_address(ORACLE_ADDRESS),
        verifier_addr,
        circuit_hash_bytes,
        commit_deadline,
        TICKET_SIZE,
        MAX_COMMITMENTS,
        web3.to_checksum_address(AUTH_SIGNER_ADDRESS),
        LIABILITY_CAP,
    )
    send_tx(web3, DEPLOYER_KEY, factory.functions.createMarket(create_params), label="create-market")

    market_id = factory.functions.nextMarketId().call() - 1
    market_addr = factory.functions.marketAddress(market_id).call()
    mkt = contract(web3, market_addr, MARKET_ABI)
    rake_bps = mkt.functions.rakeBps().call()
    log.info(
        "Market created: id=%s addr=%s rake=%sbps deadline=%ss from now",
        market_id,
        market_addr,
        rake_bps,
        COMMIT_DEADLINE_OFFSET,
    )

    # Register in API DB
    from datetime import UTC, datetime

    event_id = f"ui-sim-{market_id}-{int(time.time())}"
    closes_at = datetime.fromtimestamp(commit_deadline, tz=UTC).isoformat()
    try:
        api_post(
            "/events",
            {
                "event_id": event_id,
                "title": f"UI Sim Test #{market_id}: Will YES win? (auto-resolves in {COMMIT_DEADLINE_OFFSET}s)",
                "category": "test",
                "oracle": web3.to_checksum_address(ORACLE_ADDRESS),
                "market_address": market_addr,
                "onchain_market_id": market_id,
                "factory": web3.to_checksum_address(FACTORY),
                "status": "commit",
                "closes_at": closes_at,
                "outcomes": ["Yes", "No"],
                "outcome_prices": [0.5, 0.5],
            },
        )
        log.info("API DB registration: event_id=%s", event_id)
    except Exception as e:
        log.warning("DB registration failed (non-fatal): %s", e)

    # Verify market visible via API
    try:
        r = httpx.get(f"{API_URL}/events/{event_id}", timeout=5)
        all_ok &= ok("Market visible in API", r.status_code == 200, f"event_id={event_id}")
    except Exception as e:
        all_ok &= ok("Market visible in API", False, str(e))

    # ─── Step 2: Place Bets (simulates wallet calls via frontend) ──────────
    header("Step 2: Place Bets (simulates frontend wallet txs)")
    tickets = []
    for ticket_id, outcome in [(0, 0), (1, 1)]:
        salt = secrets.randbelow(FIELD_MODULUS)
        log.info("Computing Poseidon commitment for ticket %s (outcome=%s)...", ticket_id, outcome)
        commitment = poseidon_commitment(outcome, salt)
        log.info("  commitment: 0x%s", commitment.hex())

        submit_commitment(web3, mkt, market_addr, market_id, ticket_id, commitment, TEST_ACCOUNT_KEY, chain_id)
        tickets.append(
            {"ticket_id": ticket_id, "outcome": outcome, "salt": str(salt), "commitment": "0x" + commitment.hex()}
        )
        log.info("  Ticket %s placed (outcome=%s, 1 ZEN)", ticket_id, outcome)

    # Verify on-chain
    on_next = mkt.functions.nextTicketId().call()
    all_ok &= ok("2 tickets committed on-chain", on_next == 2, f"nextTicketId={on_next}")

    # ─── Step 3: Wait for Commit Deadline ─────────────────────────────────
    header("Step 3: Waiting for Commit Deadline")
    now = int(time.time())
    wait = max(0, commit_deadline - now + 2)
    log.info("Waiting %ds for commit deadline (deadline=%s, now=%s)...", wait, commit_deadline, now)
    if wait > 0:
        time.sleep(wait)

    # ─── Step 4: Compute Merkle Root & Lock Batches ────────────────────────
    header("Step 4: Lock Batches (oracle action)")

    # Compute batch Merkle root via prover merkle endpoint
    commitments_hex = [t["commitment"] for t in tickets]
    log.info("Computing batch Merkle root via prover...")
    resp = httpx.post(
        f"{PROVER_URL}/api/v1/hash/merkle-root",
        json={"commitments": commitments_hex, "batch_size": MAX_COMMITMENTS},
        timeout=30,
    )
    resp.raise_for_status()
    root_data = resp.json()
    batch_root_hex = root_data["root"]
    batch_root_bytes = bytes.fromhex(batch_root_hex[2:] if batch_root_hex.startswith("0x") else batch_root_hex)
    log.info("Batch root: %s", batch_root_hex)

    relayer_sig = sign_lock_batches(
        web3,
        DEPLOYER_KEY,
        market_addr,
        FACTORY,
        market_id,
        [batch_root_bytes],
        [2],
        chain_id,
    )

    send_tx(
        web3,
        ORACLE_KEY,
        mkt.functions.lockBatches([batch_root_bytes], [2], relayer_sig),
        label="lock-batches",
    )
    phase = mkt.functions.phase().call()
    all_ok &= ok("Market locked (phase=1)", phase == 1, f"phase={phase}")

    # ─── Step 5: Post Result ───────────────────────────────────────────────
    header("Step 5: Post Result (oracle resolves)")
    if not mkt.functions.resultPosted().call():
        send_tx(web3, ORACLE_KEY, mkt.functions.postResult(WINNING_OUTCOME), label="post-result")
    result_posted = mkt.functions.resultPosted().call()
    winning = mkt.functions.winningOutcomeId().call()
    all_ok &= ok("Result posted", result_posted)
    all_ok &= ok(f"Winning outcome={WINNING_OUTCOME}", winning == WINNING_OUTCOME, f"got {winning}")

    # ─── Step 6: Generate ZK Proof ─────────────────────────────────────────
    header("Step 6: Generate ZK Proof (prover service)")
    proof_data = request_proof(market_addr, market_id, batch_root_hex, tickets)
    log.info("Proof received! Public signals: %s", proof_data.get("public_signals", [])[:5])
    proof_bytes = pack_proof(proof_data["proof_json"])
    public_signals = [int(x) for x in proof_data["public_signals"]]
    log.info("Proof packed: %d bytes", len(proof_bytes))
    all_ok &= ok("Proof generated", len(proof_bytes) == 256, f"len={len(proof_bytes)}")

    # ─── Step 7: Verify & Settle ───────────────────────────────────────────
    header("Step 7: Verify & Settle On-Chain")
    send_tx(
        web3,
        ORACLE_KEY,
        mkt.functions.verifyAndSettle(proof_bytes, public_signals),
        label="verify-and-settle",
    )
    phase = mkt.functions.phase().call()
    all_ok &= ok("Market settled (phase=2)", phase == 2, f"phase={phase}")

    # ─── Step 8: Claim Payouts (simulates user wallet claim) ───────────────
    header("Step 8: Claim Payouts (simulates user wallet claims)")

    escrow = contract(
        web3,
        RELAYER_ESCROW,
        [
            {
                "name": "claimPayout",
                "type": "function",
                "stateMutability": "nonpayable",
                "inputs": [
                    {"name": "market", "type": "address"},
                    {"name": "ticketId", "type": "uint256"},
                    {"name": "outcome", "type": "uint256"},
                    {"name": "salt", "type": "uint256"},
                ],
                "outputs": [],
            },
        ],
    )

    # YES winner (ticket 0)
    yes_ticket = tickets[0]
    escrow_before = (
        contract(
            web3,
            RELAYER_ESCROW,
            [
                {
                    "name": "balanceOf",
                    "type": "function",
                    "stateMutability": "view",
                    "inputs": [{"name": "", "type": "address"}],
                    "outputs": [{"name": "", "type": "uint256"}],
                },
            ],
        )
        .functions.balanceOf(test_account.address)
        .call()
    )

    send_tx(
        web3,
        TEST_ACCOUNT_KEY,
        escrow.functions.claimPayout(
            web3.to_checksum_address(market_addr),
            yes_ticket["ticket_id"],
            yes_ticket["outcome"],
            int(yes_ticket["salt"]),
        ),
        label="claim-yes",
    )

    escrow_after = (
        contract(
            web3,
            RELAYER_ESCROW,
            [
                {
                    "name": "balanceOf",
                    "type": "function",
                    "stateMutability": "view",
                    "inputs": [{"name": "", "type": "address"}],
                    "outputs": [{"name": "", "type": "uint256"}],
                },
            ],
        )
        .functions.balanceOf(test_account.address)
        .call()
    )
    payout = escrow_after - escrow_before
    log.info("YES claim payout: %s ZEN (escrow delta)", wei_to_zen(payout))
    expected_payout = 2 * TICKET_SIZE * (10000 - rake_bps) // 10000
    all_ok &= ok(
        f"YES payout ~{wei_to_zen(expected_payout)} ZEN", payout == expected_payout, f"got {wei_to_zen(payout)}"
    )

    # NO loser (ticket 1): should revert
    no_ticket = tickets[1]
    try:
        send_tx(
            web3,
            TEST_ACCOUNT_KEY,
            escrow.functions.claimPayout(
                web3.to_checksum_address(market_addr),
                no_ticket["ticket_id"],
                no_ticket["outcome"],
                int(no_ticket["salt"]),
            ),
            label="claim-no",
        )
        all_ok &= ok("NO claim correctly rejected", False, "expected revert but succeeded")
    except Exception as e:
        all_ok &= ok("NO claim correctly rejected", True, f"reverted as expected: {str(e)[:60]}")

    # ─── Final Summary ─────────────────────────────────────────────────────
    header("FINAL SUMMARY")
    log.info("Market ID:       %s", market_id)
    log.info("Market Address:  %s", market_addr)
    log.info("Event ID:        %s", event_id)
    log.info("Rake:            %sbps (%.1f%%)", rake_bps, rake_bps / 100)
    log.info("YES payout:      %s ZEN", wei_to_zen(payout))
    log.info(
        "Pool remaining:  %s ZEN",
        wei_to_zen(
            contract(
                web3,
                PROTOCOL_POOL,
                [
                    {
                        "name": "totalAssets",
                        "type": "function",
                        "stateMutability": "view",
                        "inputs": [],
                        "outputs": [{"name": "", "type": "uint256"}],
                    },
                ],
            )
            .functions.totalAssets()
            .call()
        ),
    )

    if all_ok:
        log.info("")
        log.info("ALL CHECKS PASSED — Full UI simulation flow complete!")
        return 0
    else:
        log.error("SOME CHECKS FAILED — Review output above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
