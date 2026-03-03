#!/usr/bin/env python3
"""Phases 4-7: Batch locking, oracle resolution, proof generation, settlement.

Contract flow: Commit → lockBatches (→ Locked) → postResult → verifyAndSettle (→ Settled)
- lockBatches requires phase==Commit AND block.timestamp >= commitDeadline AND onlyOracle
- postResult requires phase==Locked AND onlyOracle
- verifyAndSettle requires phase==Locked AND resultPosted AND onlyOracle
"""

from __future__ import annotations

import json
import sys
import time

from eth_account import Account
from eth_account.messages import encode_defunct
from poseidon import BATCH_SIZE, MERKLE_DEPTH, build_batch_root, int_to_hex32, poseidon_t3
from utils import (
    CHAIN_ID,
    CIRCUIT_HASH,
    DEPLOYER_KEY,
    FACTORY,
    MARKET_ABI,
    ORACLE_KEY,
    build_web3,
    check,
    contract,
    header,
    load_state,
    log,
    phase_name,
    prover_post,
    send_tx,
    setup_logging,
    update_state,
    wei_to_zen,
)
from web3 import Web3

WINNING_OUTCOME = 0  # YES wins


def build_merkle_tree(leaves_int: list[int], *, depth: int = MERKLE_DEPTH, pad_to: int = BATCH_SIZE) -> list[list[int]]:
    """Build a full Merkle tree (all levels) from leaves.
    Returns a list of levels, where levels[0] = leaves (padded), levels[-1] = [root].
    """
    padded = [int(v) for v in leaves_int] + [0] * (pad_to - len(leaves_int))
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
    """Extract the sibling proof path for a given leaf index."""
    proof = []
    idx = leaf_index
    for level in tree_levels[:-1]:  # skip root level
        sibling_idx = idx ^ 1  # flip last bit to get sibling
        proof.append(int_to_hex32(level[sibling_idx]))
        idx >>= 1  # move up one level
    return proof


def sign_lock_batches(
    market_address: str,
    factory_address: str,
    market_id: int,
    roots: list[bytes],
    counts: list[int],
    chain_id: int = CHAIN_ID,
    signer_key: str = DEPLOYER_KEY,
) -> bytes:
    """Sign the lockBatches relayer digest matching on-chain verification.

    The contract computes:
        abi.encode(address(this), factory, marketId, roots, counts, block.chainid)
    then keccak256 → toEthSignedMessageHash → ecrecover == RelayerEscrow.owner()
    """
    from eth_abi import encode

    # abi.encode with dynamic types (bytes32[] and uint16[])
    encoded = encode(
        ["address", "address", "uint256", "bytes32[]", "uint16[]", "uint256"],
        [
            Web3.to_checksum_address(market_address),
            Web3.to_checksum_address(factory_address),
            market_id,
            roots,
            counts,
            chain_id,
        ],
    )
    digest = Web3.keccak(encoded)
    signed = Account.sign_message(encode_defunct(digest), signer_key)
    return signed.signature


def main() -> int:
    setup_logging()

    state = load_state()
    market_address = state["market_address"]
    market_id = state["market_id"]
    tickets = state["tickets"]
    rake_bps = state.get("rake_bps", 0)
    commit_deadline = state.get("commit_deadline", 0)

    web3 = build_web3()
    market_contract = contract(web3, market_address, MARKET_ABI)

    # =====================================================================
    # Phase 4: Lock Batches (must happen BEFORE oracle resolution)
    # Contract requires: phase==Commit, block.timestamp >= commitDeadline
    # =====================================================================
    header("Phase 4: Lock Batches")

    phase = market_contract.functions.phase().call()
    log.info("Current phase: %s (%s)", phase, phase_name(phase))

    if phase == 1:
        log.info("Market already locked, skipping lockBatches")
    elif phase != 0:
        log.error("Market is not in Commit or Locked phase! phase=%s", phase)
        return 1
    else:
        # Wait for commit deadline to pass
        now = int(time.time())
        if commit_deadline > 0 and now < commit_deadline:
            wait_secs = commit_deadline - now + 5  # +5s buffer
            log.info("Commit deadline not yet passed. Waiting %ds...", wait_secs)
            log.info("  Current time: %s  Deadline: %s", now, commit_deadline)
            time.sleep(wait_secs)
            log.info("Deadline should have passed now")

        # Build ticket data
        leaf_ints = []
        for t in tickets:
            leaf_ints.append(int(t["leaf_int"]))

        # Compute expected batch root locally
        batch_root_int = build_batch_root(leaf_ints)
        batch_root_hex = int_to_hex32(batch_root_int)
        log.info("Expected batch root: %s", batch_root_hex)
        log.info("Ticket count: %s", len(tickets))

        # Build Merkle tree for proof extraction later
        tree_levels = build_merkle_tree(leaf_ints)
        computed_root = int_to_hex32(tree_levels[-1][0])
        log.info("Tree root (verify): %s", computed_root)
        check("Merkle root matches batch root", computed_root == batch_root_hex)

        # Extract Merkle proofs for each ticket (needed for claiming)
        merkle_proofs = {}
        for t in tickets:
            tid = t["ticket_id"]
            leaf_index = tid % BATCH_SIZE
            proof = extract_merkle_proof(tree_levels, leaf_index)
            merkle_proofs[tid] = proof
            log.info("Merkle proof for ticket %s: %d siblings", tid, len(proof))

        # Sign relayer digest (deployer is escrow owner)
        batch_roots_bytes = [bytes.fromhex(batch_root_hex[2:])]
        batch_counts = [len(tickets)]

        log.info("Signing lock-batches relayer digest with deployer key...")
        relayer_sig = sign_lock_batches(
            market_address=market_address,
            factory_address=FACTORY,
            market_id=market_id,
            roots=batch_roots_bytes,
            counts=batch_counts,
        )
        log.info("  relayer sig: 0x%s...%s (%d bytes)", relayer_sig[:4].hex(), relayer_sig[-4:].hex(), len(relayer_sig))

        # Oracle calls lockBatches (onlyOracle modifier)
        log.info("Calling lockBatches on-chain via oracle...")
        send_tx(
            web3,
            ORACLE_KEY,
            market_contract.functions.lockBatches(batch_roots_bytes, batch_counts, relayer_sig),
            label="lock-batches",
        )

    # Verify lock
    phase = market_contract.functions.phase().call()
    log.info("Phase after lock: %s (%s)", phase, phase_name(phase))

    # Re-compute merkle data if we skipped the lock (phase was already 1)
    leaf_ints = [int(t["leaf_int"]) for t in tickets]
    batch_root_int = build_batch_root(leaf_ints)
    batch_root_hex = int_to_hex32(batch_root_int)
    tree_levels = build_merkle_tree(leaf_ints)
    merkle_proofs = {}
    for t in tickets:
        tid = t["ticket_id"]
        leaf_index = tid % BATCH_SIZE
        proof = extract_merkle_proof(tree_levels, leaf_index)
        merkle_proofs[tid] = proof

    on_chain_root = market_contract.functions.batchRoots(0).call()
    on_chain_root_hex = "0x" + on_chain_root.hex()
    on_chain_count = market_contract.functions.batchCounts(0).call()

    log.info("On-chain batchRoot[0]:  %s", on_chain_root_hex)
    log.info("On-chain batchCount[0]: %s", on_chain_count)

    all_ok = True
    all_ok &= check("Phase is Locked (1)", phase == 1, f"got {phase}")
    all_ok &= check("Batch root matches", on_chain_root_hex == batch_root_hex)
    all_ok &= check("Batch count matches", on_chain_count == len(tickets), f"got {on_chain_count}")

    update_state(
        batch_root=batch_root_hex,
        batch_count=len(tickets),
        merkle_proofs={str(k): v for k, v in merkle_proofs.items()},
        phase4_complete=True,
    )

    # =====================================================================
    # Phase 5: Oracle Resolution (post winning outcome)
    # Contract requires: phase==Locked, onlyOracle
    # =====================================================================
    header("Phase 5: Oracle Resolution")

    oracle = Account.from_key(ORACLE_KEY)
    log.info("Oracle: %s", oracle.address)
    log.info("Posting result: outcome=%s (YES wins)", WINNING_OUTCOME)

    phase = market_contract.functions.phase().call()
    log.info("Current phase: %s (%s)", phase, phase_name(phase))

    result_already_posted = market_contract.functions.resultPosted().call()
    if result_already_posted:
        log.info("Result already posted, skipping postResult")
    elif phase != 1:
        log.warning("Market not in Locked phase (phase=%s), cannot post result", phase)
    else:
        send_tx(
            web3,
            ORACLE_KEY,
            market_contract.functions.postResult(WINNING_OUTCOME),
            label="post-result",
        )

    # Verify
    winning = market_contract.functions.winningOutcomeId().call()
    log.info("winningOutcomeId: %s", winning)
    check("Winning outcome recorded", winning == WINNING_OUTCOME, f"got {winning}")

    update_state(winning_outcome=WINNING_OUTCOME, phase5_complete=True)

    # =====================================================================
    # Phase 6: Proof Generation
    # =====================================================================
    header("Phase 6: Proof Generation")

    # Build prover request with exactly 256 tickets (pad with zeros)
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

    # Pad to 256 with zero tickets
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

    # Pool totals: sum of amounts by outcome (amounts are already net of rake)
    pool_yes = sum(int(t["amount"]) for t in tickets if t["outcome_id"] == 0)
    pool_no = sum(int(t["amount"]) for t in tickets if t["outcome_id"] == 1)
    total_escrow = pool_yes + pool_no
    # Settlement invariant: totalLiability = poolYes + poolNo = totalEscrow
    # (rake was already deducted from ticket amounts before entering the pool)
    total_liability = total_escrow

    # Cross-validate against on-chain state
    on_chain_escrow = market_contract.functions.totalEscrow().call()
    on_chain_rake = market_contract.functions.rakeBps().call()
    check(
        "totalEscrow matches on-chain",
        total_escrow == on_chain_escrow,
        f"computed={wei_to_zen(total_escrow)}, on-chain={wei_to_zen(on_chain_escrow)}",
    )
    check("rakeBps matches on-chain", rake_bps == on_chain_rake, f"state={rake_bps}, on-chain={on_chain_rake}")

    prover_request = {
        "marketId": str(market_id),
        "merkleRoot": batch_root_hex,
        "winningOutcomeId": str(WINNING_OUTCOME),
        "poolTotals": [str(pool_yes), str(pool_no)],
        "totalEscrow": str(total_escrow),
        "totalLiability": str(total_liability),
        "rakeBps": str(rake_bps),
        "circuitHash": CIRCUIT_HASH,
        "batchIndex": "0",
        "commitmentsCount": str(len(tickets)),
        "tickets": prover_tickets,
    }

    log.info("Prover request:")
    log.info("  marketId:         %s", market_id)
    log.info("  merkleRoot:       %s", batch_root_hex)
    log.info("  winningOutcomeId: %s", WINNING_OUTCOME)
    log.info("  poolTotals:       [%s, %s]", wei_to_zen(pool_yes), wei_to_zen(pool_no))
    log.info("  totalEscrow:      %s", wei_to_zen(total_escrow))
    log.info("  totalLiability:   %s", wei_to_zen(total_liability))
    log.info("  rakeBps:          %s", rake_bps)
    log.info("  commitmentsCount: %s", len(tickets))

    log.info("Submitting proof request to prover...")
    start_time = time.time()
    proof_response = prover_post("/api/v1/proofs/settlement", prover_request)
    elapsed = time.time() - start_time
    log.info("Proof generated in %.1fs", elapsed)

    # Parse proof response
    proof_json = proof_response.get("proof", "")
    public_signals = proof_response.get("public_signals", [])
    proof_calldata = proof_response.get("proof_calldata", [])
    warnings = proof_response.get("warnings", [])

    log.info("Public signals (%d): %s", len(public_signals), public_signals[:3])
    if warnings:
        log.warning("Prover warnings: %s", warnings)

    check("Got valid proof", bool(proof_json), "proof present")
    check("Got 10 public signals", len(public_signals) == 10, f"got {len(public_signals)}")

    update_state(
        proof_json=proof_json,
        public_signals=public_signals,
        proof_calldata=proof_calldata,
        pool_yes=str(pool_yes),
        pool_no=str(pool_no),
        total_escrow=str(total_escrow),
        total_liability=str(total_liability),
        phase6_complete=True,
    )

    # =====================================================================
    # Phase 7: Settlement (On-Chain Proof Verification)
    # =====================================================================
    header("Phase 7: Settlement")

    phase = market_contract.functions.phase().call()
    log.info("Phase before settlement: %s (%s)", phase, phase_name(phase))

    # Build calldata from proof_calldata
    if proof_calldata and len(proof_calldata) >= 2:
        # The proof needs to be ABI-encoded as bytes
        # Parse the proof JSON to get a, b, c points
        if isinstance(proof_json, str):
            proof_parsed = json.loads(proof_json.rstrip("\x00"))
        else:
            proof_parsed = proof_json

        pi_a = proof_parsed["pi_a"][:2]  # [x, y] (skip z=1)
        pi_b = proof_parsed["pi_b"][:2]  # [[x1, x2], [y1, y2]] (skip z)
        pi_c = proof_parsed["pi_c"][:2]  # [x, y] (skip z=1)

        # Encode proof as packed bytes: a[0], a[1], b[0][0], b[0][1], b[1][0], b[1][1], c[0], c[1]
        # Each uint256 is 32 bytes
        proof_bytes = b""
        proof_bytes += int(pi_a[0]).to_bytes(32, "big")
        proof_bytes += int(pi_a[1]).to_bytes(32, "big")
        # Note: Solidity Groth16 verifiers typically expect b swapped
        proof_bytes += int(pi_b[0][1]).to_bytes(32, "big")
        proof_bytes += int(pi_b[0][0]).to_bytes(32, "big")
        proof_bytes += int(pi_b[1][1]).to_bytes(32, "big")
        proof_bytes += int(pi_b[1][0]).to_bytes(32, "big")
        proof_bytes += int(pi_c[0]).to_bytes(32, "big")
        proof_bytes += int(pi_c[1]).to_bytes(32, "big")

        # Public signals as uint256[10]
        pub_signals_int = [int(s) for s in public_signals]

        log.info("Submitting verifyAndSettle on-chain...")
        log.info("  proof bytes: %d bytes", len(proof_bytes))
        log.info("  public signals: %s", [str(s)[:20] + "..." for s in pub_signals_int[:3]])

        try:
            send_tx(
                web3,
                ORACLE_KEY,
                market_contract.functions.verifyAndSettle(proof_bytes, pub_signals_int),
                label="verify-settle",
            )
        except Exception as exc:
            log.warning("verifyAndSettle failed: %s", exc)
            log.info("Trying verifyAndSettleBatched with batch index 0...")
            try:
                send_tx(
                    web3,
                    ORACLE_KEY,
                    market_contract.functions.verifyAndSettleBatched(
                        [proof_bytes],
                        [pub_signals_int],
                        [0],
                    ),
                    label="verify-settle-batched",
                )
            except Exception as exc2:
                log.error("verifyAndSettleBatched also failed: %s", exc2)
                return 1
    else:
        log.error("No proof calldata available — cannot settle")
        return 1

    # Verify settlement
    phase = market_contract.functions.phase().call()
    log.info("Phase after settlement: %s (%s)", phase, phase_name(phase))
    batch_verified = market_contract.functions.batchProofVerified(0).call()
    log.info("batchProofVerified[0]: %s", batch_verified)

    check("Phase is Settled (2)", phase == 2, f"got {phase}")
    check("Batch proof verified", batch_verified)

    update_state(phase7_complete=True)

    log.info("")
    log.info("Phases 4-7 COMPLETE - Market locked, resolved, proved, and settled.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
