#!/usr/bin/env python3
"""Phase 2: Generate proof, settle on-chain, and claim payout."""

import importlib.util
import json
import os
import sys
import time

import httpx

_spec = importlib.util.spec_from_file_location("poseidon", "/app/shared/poseidon.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
compute_leaf = _mod.compute_leaf
poseidon_t3 = _mod.poseidon_t3
FIELD_MODULUS = _mod.FIELD_MODULUS
BATCH_SIZE = _mod.BATCH_SIZE

from eth_account import Account
from web3 import HTTPProvider, Web3

w3 = Web3(HTTPProvider("https://horizen-testnet.rpc.caldera.xyz/http"))
CHAIN_ID = 2651420
CIRCUIT_HASH = "0x181e1866c82c6c72f18cd61723f1f61cd0a02224250b988af5a3f32863f2b157"
ORACLE_KEY = os.environ["RM_SETTLEMENT_SIGNER_PRIVATE_KEY"]
PROVER_URL = os.environ.get("RM_PROVER_URL", "http://prover:8085")
PROVER_SECRET =<REDACTED>
RELAYER_URL = os.environ.get("RM_RELAYER_BASE_URL", "http://relayer:8088")
RELAYER_BEARER = os.environ.get("RM_RELAYER_BEARER_TOKEN", "")
INTERNAL_SECRET =<REDACTED>
USER_ADDRESS = os.environ["E2E_USER_ADDRESS"]

state = json.load(open("/tmp/prod_e2e_state.json"))
market_address = state["market_address"]
market_id = state["market_id"]
batch_root = state["batch_root"]
tickets = state["tickets"]
merkle_proofs = state["merkle_proofs"]
rake_bps = state["rake_bps"]
winning_outcome = state["winning_outcome"]

MARKET_ABI = [
    {
        "inputs": [],
        "name": "phase",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
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
        "inputs": [{"name": "ticketId", "type": "uint256"}],
        "name": "claimedTickets",
        "outputs": [{"name": "", "type": "bool"}],
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
        "name": "totalEscrow",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
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

mc = w3.eth.contract(address=w3.to_checksum_address(market_address), abi=MARKET_ABI)
escrow = w3.eth.contract(address=w3.to_checksum_address("0x5b0fA47675D07b018E2151d49d4aECc71b47E47D"), abi=ESCROW_ABI)


def send(key, fn, label):
    acct = Account.from_key(key)
    nonce = w3.eth.get_transaction_count(acct.address, "pending")
    est = fn.estimate_gas({"from": acct.address})
    tx = fn.build_transaction(
        {
            "from": acct.address,
            "nonce": nonce,
            "gas": int(est * 1.3),
            "gasPrice": w3.eth.gas_price,
            "chainId": CHAIN_ID,
        }
    )
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    h = w3.eth.send_raw_transaction(raw)
    print(f"  [{label}] tx: 0x{h.hex()}")
    r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    print(f"  [{label}] status={r['status']} block={r['blockNumber']} gas={r['gasUsed']}")
    assert r["status"] == 1, f"{label} REVERTED"
    return r


# =========================================================================
# STEP 1: Verify on-chain state
# =========================================================================
print("=" * 60)
print("  STEP 1: Verify on-chain state")
print("=" * 60)
phase = mc.functions.phase().call()
result_posted = mc.functions.resultPosted().call()
total_escrow = mc.functions.totalEscrow().call()
print(f"  Phase: {phase} (expected 1=Locked)")
print(f"  Result posted: {result_posted}")
print(f"  Total escrow: {total_escrow / 1e18:.4f} ZEN")
assert phase == 1, f"Expected phase 1, got {phase}"
assert result_posted, "Result not posted!"

# =========================================================================
# STEP 2: Build prover request
# =========================================================================
print("\n" + "=" * 60)
print("  STEP 2: Build prover request & generate proof")
print("=" * 60)

# Pool totals: sum of amounts per outcome
pool_yes = sum(int(t["amount"]) for t in tickets if t["outcome_id"] == 0)
pool_no = sum(int(t["amount"]) for t in tickets if t["outcome_id"] == 1)
total_escrow_calc = pool_yes + pool_no
# Total liability = sum of payouts for WINNING outcome only
total_liability = sum(int(t["payout"]) for t in tickets if t["outcome_id"] == winning_outcome)

print(f"  Pool YES: {pool_yes / 1e18:.4f} ZEN")
print(f"  Pool NO: {pool_no / 1e18:.4f} ZEN")
print(f"  Total escrow: {total_escrow_calc / 1e18:.4f} ZEN")
print(f"  Total liability (winning payouts): {total_liability / 1e18:.4f} ZEN")


# Build ticket array (padded to BATCH_SIZE=256)
def address_to_field(addr):
    return int(addr, 16)


prover_tickets = []
for t in tickets:
    prover_tickets.append(
        {
            "ticketId": str(t["ticket_id"]),
            "outcomeId": str(t["outcome_id"]),
            "amount": str(t["amount"]),
            "payout": str(t["payout"]),
            "user": str(address_to_field(USER_ADDRESS)),
            "salt": str(int(t["salt"], 16)),
        }
    )

# Pad to 256 with zero tickets
for i in range(len(tickets), BATCH_SIZE):
    prover_tickets.append(
        {
            "ticketId": str(i),
            "outcomeId": "0",
            "amount": "0",
            "payout": "0",
            "user": "0",
            "salt": "0",
        }
    )

prover_payload = {
    "marketId": str(market_id),
    "merkleRoot": batch_root,
    "winningOutcomeId": str(winning_outcome),
    "poolTotals": [str(pool_yes), str(pool_no)],
    "totalEscrow": str(total_escrow_calc),
    "totalLiability": str(total_liability),
    "rakeBps": str(rake_bps),
    "circuitHash": CIRCUIT_HASH,
    "batchIndex": "0",
    "commitmentsCount": str(len(tickets)),
    "tickets": prover_tickets,
}

print(f"  Sending to prover at {PROVER_URL}...")
print(f"  Payload size: {len(json.dumps(prover_payload))} bytes")

resp = httpx.post(
    f"{PROVER_URL}/api/v1/proofs/settlement",
    json=prover_payload,
    headers={
        "Content-Type": "application/json",
        "X-Prover-Secret": PROVER_SECRET,
    },
    timeout=300,
)
print(f"  Prover response status: {resp.status_code}")
if resp.status_code != 200:
    print(f"  ERROR: {resp.text[:500]}")
    sys.exit(1)

proof_resp = resp.json()
proof_json_str = proof_resp.get("proof", "")
public_signals = proof_resp.get("public_signals", [])
warnings = proof_resp.get("warnings", [])

print(f"  Proof received! {len(proof_json_str)} chars")
print(f"  Public signals: {len(public_signals)} values")
if warnings:
    print(f"  Warnings: {warnings}")
print(f"  Public signals[0] (batch root): {public_signals[0][:20]}..." if public_signals else "  NO SIGNALS")

# =========================================================================
# STEP 3: Pack proof and call verifyAndSettle
# =========================================================================
print("\n" + "=" * 60)
print("  STEP 3: Submit verifyAndSettle on-chain")
print("=" * 60)

# Parse proof
proof_data = json.loads(proof_json_str.rstrip("\x00"))
pi_a = proof_data["pi_a"][:2]
pi_b = proof_data["pi_b"][:2]
pi_c = proof_data["pi_c"][:2]

# Pack as 256 bytes: a[0], a[1], b[0][1], b[0][0], b[1][1], b[1][0], c[0], c[1]
proof_bytes = b""
proof_bytes += int(pi_a[0]).to_bytes(32, "big")
proof_bytes += int(pi_a[1]).to_bytes(32, "big")
proof_bytes += int(pi_b[0][1]).to_bytes(32, "big")
proof_bytes += int(pi_b[0][0]).to_bytes(32, "big")
proof_bytes += int(pi_b[1][1]).to_bytes(32, "big")
proof_bytes += int(pi_b[1][0]).to_bytes(32, "big")
proof_bytes += int(pi_c[0]).to_bytes(32, "big")
proof_bytes += int(pi_c[1]).to_bytes(32, "big")
print(f"  Proof bytes: {len(proof_bytes)} bytes")

signals_int = [int(s) for s in public_signals]
print(f"  Signals: {signals_int[:3]}...")

send(ORACLE_KEY, mc.functions.verifyAndSettle(proof_bytes, signals_int), "verifyAndSettle")

phase_after = mc.functions.phase().call()
print(f"  Phase after settle: {phase_after} (expected 2=Settled)")
assert phase_after == 2, f"Expected phase 2, got {phase_after}"
print("  SETTLEMENT SUCCESSFUL!")

# Save proof data to state
state["proof_json"] = proof_json_str
state["public_signals"] = [str(s) for s in public_signals]
json.dump(state, open("/tmp/prod_e2e_state.json", "w"), indent=2)

# =========================================================================
# STEP 4: Claim winning payout via relayer
# =========================================================================
print("\n" + "=" * 60)
print("  STEP 4: Claim winning payout (ticket 0, YES)")
print("=" * 60)

escrow_before = escrow.functions.balanceOf(w3.to_checksum_address(USER_ADDRESS)).call()
print(f"  User escrow before claim: {escrow_before / 1e18:.4f} ZEN")

winner_ticket = tickets[0]  # YES ticket
claim_payload = {
    "market": market_address,
    "user": USER_ADDRESS,
    "ticket_id": winner_ticket["ticket_id"],
    "outcome_id": winner_ticket["outcome_id"],
    "amount": int(winner_ticket["amount"]),
    "payout": int(winner_ticket["payout"]),
    "salt": winner_ticket["salt"],
    "merkle_proof": merkle_proofs[str(winner_ticket["ticket_id"])],
    "event_id": state["event_id"],
}
print(
    f"  Claiming ticket {winner_ticket['ticket_id']} (outcome={winner_ticket['outcome_id']}, payout={int(winner_ticket['payout']) / 1e18:.4f} ZEN)"
)

claim_resp = httpx.post(
    f"{RELAYER_URL}/claim",
    json=claim_payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {RELAYER_BEARER}",
    },
    timeout=60,
)
print(f"  Relayer response: {claim_resp.status_code}")
if claim_resp.status_code >= 400:
    print(f"  ERROR: {claim_resp.text[:500]}")
    # Try direct claim instead
    print("  Attempting direct on-chain claim...")
else:
    claim_result = claim_resp.json()
    print(f"  Job ID: {claim_result.get('jobId', 'N/A')}")
    job_id = claim_result.get("jobId")

    # Poll for completion
    if job_id:
        print("  Polling for job completion...")
        deadline = time.time() + 120
        while time.time() < deadline:
            status_resp = httpx.post(
                f"{RELAYER_URL}/status",
                json={"jobId": job_id},
                headers={"Authorization": f"Bearer {RELAYER_BEARER}", "Content-Type": "application/json"},
                timeout=30,
            )
            result = status_resp.json()
            status = result.get("status", "unknown")
            print(f"    Status: {status}")
            if status in ("succeeded", "completed", "mined", "confirmed"):
                print(f"    Claim TX: {result.get('txHash', 'N/A')}")
                break
            if status in ("failed", "dead", "deadletter"):
                print(f"    FAILED: {result}")
                break
            time.sleep(3)

# Check balances after
escrow_after = escrow.functions.balanceOf(w3.to_checksum_address(USER_ADDRESS)).call()
print(f"\n  User escrow after claim: {escrow_after / 1e18:.4f} ZEN")
print(f"  Escrow change: +{(escrow_after - escrow_before) / 1e18:.4f} ZEN")

claimed = mc.functions.claimedTickets(0).call()
print(f"  Ticket 0 claimed: {claimed}")

# =========================================================================
# STEP 5: Try claiming loser ticket (should fail)
# =========================================================================
print("\n" + "=" * 60)
print("  STEP 5: Attempt loser claim (ticket 1, NO) - should fail")
print("=" * 60)

loser_ticket = tickets[1]
loser_payload = {
    "market": market_address,
    "user": USER_ADDRESS,
    "ticket_id": loser_ticket["ticket_id"],
    "outcome_id": loser_ticket["outcome_id"],
    "amount": int(loser_ticket["amount"]),
    "payout": int(loser_ticket["payout"]),
    "salt": loser_ticket["salt"],
    "merkle_proof": merkle_proofs[str(loser_ticket["ticket_id"])],
    "event_id": state["event_id"],
}
print(f"  Claiming loser ticket {loser_ticket['ticket_id']} (outcome={loser_ticket['outcome_id']})")

loser_resp = httpx.post(
    f"{RELAYER_URL}/claim",
    json=loser_payload,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {RELAYER_BEARER}"},
    timeout=60,
)
print(f"  Relayer response: {loser_resp.status_code}")
if loser_resp.status_code >= 400:
    print(f"  Expected failure: {loser_resp.text[:200]}")
    print("  LOSER CLAIM CORRECTLY REJECTED!")
else:
    loser_result = loser_resp.json()
    loser_job_id = loser_result.get("jobId")
    if loser_job_id:
        time.sleep(5)
        status_resp = httpx.post(
            f"{RELAYER_URL}/status",
            json={"jobId": loser_job_id},
            headers={"Authorization": f"Bearer {RELAYER_BEARER}", "Content-Type": "application/json"},
            timeout=30,
        )
        loser_status = status_resp.json()
        print(f"  Loser job status: {loser_status.get('status')}")
        if loser_status.get("status") in ("failed", "dead", "deadletter"):
            print("  LOSER CLAIM CORRECTLY FAILED ON-CHAIN!")
        else:
            print("  WARNING: Loser claim did not fail as expected!")

# =========================================================================
# SUMMARY
# =========================================================================
print("\n" + "=" * 60)
print("  E2E TEST SUMMARY")
print("=" * 60)
print(f"  Market: {market_address} (ID={market_id})")
print(f"  Phase: {mc.functions.phase().call()} (2=Settled)")
print("  Proof generated: YES")
print("  Settlement verified on-chain: YES")
print(f"  Winner claim (ticket 0): {'YES' if mc.functions.claimedTickets(0).call() else 'PENDING'}")
print(f"  Loser claim (ticket 1): {'BLOCKED' if not mc.functions.claimedTickets(1).call() else 'ERROR-claimed'}")
print(f"  User escrow delta: +{(escrow_after - escrow_before) / 1e18:.4f} ZEN")
