#!/usr/bin/env python3
"""Phase 3: Place YES and NO bets via direct on-chain commitOnBehalf."""

from __future__ import annotations

import secrets
import sys
import time

from eth_account import Account
from poseidon import FIELD_MODULUS, compute_leaf, int_to_hex32
from utils import (
    ESCROW_ABI,
    MARKET_ABI,
    RELAYER_ESCROW,
    TEST_ACCOUNT_KEY,
    build_web3,
    check,
    contract,
    header,
    load_state,
    log,
    phase_name,
    send_tx,
    setup_logging,
    sign_commit_auth,
    update_state,
    wei_to_zen,
)
from web3 import Web3

# Number of bets per side in this E2E test (1 YES + 1 NO)
NUM_TICKETS = 2

# Correct ABI for commitOnBehalf including ticketId in CommitAuth
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
    }
]


def compute_net_amount(ticket_size: int, rake_bps: int) -> int:
    return ticket_size - (ticket_size * rake_bps // 10_000)


def place_bet(
    web3,
    market_address: str,
    market_id: int,
    ticket_id: int,
    outcome_id: int,
    user_address: str,
    event_id: str,
    *,
    ticket_size: int,
    rake_bps: int,
    payout: int,
) -> dict:
    """Place a single bet by calling commitOnBehalf directly on-chain."""
    net_amount = compute_net_amount(ticket_size, rake_bps)
    # Salt must be < BN254 SNARK_SCALAR_FIELD, otherwise on-chain _computeLeaf reverts
    salt_int = secrets.randbelow(FIELD_MODULUS)
    salt = "0x" + salt_int.to_bytes(32, "big").hex()

    log.info("Computing Poseidon leaf for ticket_id=%s outcome=%s", ticket_id, outcome_id)
    leaf_int = compute_leaf(ticket_id, outcome_id, net_amount, payout, user_address, salt)
    commitment = int_to_hex32(leaf_int)
    log.info("  leaf:       %s", commitment)
    log.info("  salt:       %s", salt)

    nonce = secrets.randbits(256)
    expiry = int(time.time()) + 600  # 10 minutes

    # Sign CommitAuth (includes ticketId per on-chain verification)
    commitment_bytes = bytes.fromhex(commitment[2:])
    signature = sign_commit_auth(
        market_address=market_address,
        market_id=market_id,
        ticket_id=ticket_id,
        commitment=commitment_bytes,
        user_address=user_address,
        nonce=nonce,
        expiry=expiry,
        ticket_value_wei=ticket_size,
    )
    signature_bytes = bytes.fromhex(signature[2:])
    log.info("  signature:  %s...%s", signature[:20], signature[-8:])

    # Build the CommitAuth tuple (with ticketId)
    auth_tuple = (
        commitment_bytes,  # commitment (bytes32)
        ticket_id,  # ticketId (uint256)
        Web3.to_checksum_address(user_address),  # user (address)
        nonce,  # nonce (uint256)
        expiry,  # expiry (uint256)
        ticket_size,  # ticketValue (uint256)
    )

    # Escrow owner calls commitOnBehalf directly (bypassing relayer HTTP API)
    # Note: escrow owner is the deployer, not the relayer address
    from utils import DEPLOYER_KEY

    escrow_direct = web3.eth.contract(
        address=Web3.to_checksum_address(RELAYER_ESCROW),
        abi=COMMIT_ON_BEHALF_ABI,
    )
    log.info("Calling commitOnBehalf directly on escrow (via deployer/owner)...")
    receipt = send_tx(
        web3,
        DEPLOYER_KEY,
        escrow_direct.functions.commitOnBehalf(
            Web3.to_checksum_address(user_address),
            Web3.to_checksum_address(market_address),
            auth_tuple,
            signature_bytes,
        ),
        label=f"commit-on-behalf-{ticket_id}",
    )
    tx_hash = receipt.get("transactionHash", b"").hex() if isinstance(receipt.get("transactionHash"), bytes) else "ok"

    return {
        "ticket_id": ticket_id,
        "outcome_id": outcome_id,
        "amount": net_amount,
        "payout": payout,
        "user": user_address,
        "salt": salt,
        "leaf": commitment,
        "leaf_int": leaf_int,
        "nonce": nonce,
        "tx_hash": tx_hash,
    }


def main() -> int:
    setup_logging()
    header("Phase 3: Place Bets (YES + NO Commitments)")

    state = load_state()
    market_address = state["market_address"]
    market_id = state["market_id"]
    event_id = state["event_id"]

    web3 = build_web3()
    market = contract(web3, market_address, MARKET_ABI)
    test_account = Account.from_key(TEST_ACCOUNT_KEY)

    log.info("Market:       %s (id=%s)", market_address, market_id)
    log.info("Test account: %s", test_account.address)
    log.info("Event ID:     %s", event_id)

    # Read market parameters from chain
    ticket_size = market.functions.ticketSize().call()
    rake_bps = market.functions.rakeBps().call()
    net_amount = compute_net_amount(ticket_size, rake_bps)
    # Pari-mutuel payout: winner takes entire pot (all net amounts from both sides)
    payout = NUM_TICKETS * net_amount

    log.info("Ticket size:  %s", wei_to_zen(ticket_size))
    log.info("Rake BPS:     %s (%s%%)", rake_bps, rake_bps / 100)
    log.info("Net amount:   %s", wei_to_zen(net_amount))
    log.info("Payout:       %s", wei_to_zen(payout))

    # Check current state
    next_ticket = market.functions.nextTicketId().call()
    phase = market.functions.phase().call()
    log.info("Current nextTicketId: %s", next_ticket)
    log.info("Current phase:        %s (%s)", phase, phase_name(phase))

    if phase != 0:
        log.error("Market is not in Commit phase! phase=%s", phase)
        return 1

    # Check escrow balance
    escrow = contract(web3, RELAYER_ESCROW, ESCROW_ABI)
    escrow_bal = escrow.functions.balanceOf(test_account.address).call()
    log.info("Escrow balance:       %s", wei_to_zen(escrow_bal))
    if escrow_bal < ticket_size * NUM_TICKETS:
        log.error(
            "Insufficient escrow balance for %d bets: have %s, need %s",
            NUM_TICKETS,
            wei_to_zen(escrow_bal),
            wei_to_zen(ticket_size * NUM_TICKETS),
        )
        return 1

    # -----------------------------------------------------------------------
    # 3.1 Commit YES (ticket_id = next available)
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 3.1 Commit YES ---")
    yes_ticket = place_bet(
        web3,
        market_address,
        market_id,
        ticket_id=next_ticket,
        outcome_id=0,  # YES
        user_address=test_account.address,
        event_id=event_id,
        ticket_size=ticket_size,
        rake_bps=rake_bps,
        payout=payout,
    )
    log.info("YES bet placed! ticket_id=%s", yes_ticket["ticket_id"])

    # -----------------------------------------------------------------------
    # 3.2 Commit NO (ticket_id = next available + 1)
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 3.2 Commit NO ---")
    no_ticket = place_bet(
        web3,
        market_address,
        market_id,
        ticket_id=next_ticket + 1,
        outcome_id=1,  # NO
        user_address=test_account.address,
        event_id=event_id,
        ticket_size=ticket_size,
        rake_bps=rake_bps,
        payout=payout,
    )
    log.info("NO bet placed! ticket_id=%s", no_ticket["ticket_id"])

    # -----------------------------------------------------------------------
    # 3.3 Verify Commitments On-Chain
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 3.3 Verify Commitments ---")

    new_next_ticket = market.functions.nextTicketId().call()
    log.info("nextTicketId after bets: %s", new_next_ticket)

    # Read stored commitments from chain
    yes_stored = market.functions.commitmentAt(yes_ticket["ticket_id"]).call()
    no_stored = market.functions.commitmentAt(no_ticket["ticket_id"]).call()
    yes_stored_hex = "0x" + yes_stored.hex()
    no_stored_hex = "0x" + no_stored.hex()

    log.info("YES on-chain commitment: %s", yes_stored_hex)
    log.info("YES expected commitment: %s", yes_ticket["leaf"])
    log.info("NO  on-chain commitment: %s", no_stored_hex)
    log.info("NO  expected commitment: %s", no_ticket["leaf"])

    all_ok = True
    all_ok &= check(
        "nextTicketId incremented",
        new_next_ticket == next_ticket + 2,
        f"expected {next_ticket + 2}, got {new_next_ticket}",
    )
    all_ok &= check("YES leaf matches on-chain", yes_stored_hex == yes_ticket["leaf"])
    all_ok &= check("NO leaf matches on-chain", no_stored_hex == no_ticket["leaf"])

    # Save ticket details for later phases
    update_state(
        tickets=[
            {
                "ticket_id": yes_ticket["ticket_id"],
                "outcome_id": yes_ticket["outcome_id"],
                "amount": str(yes_ticket["amount"]),
                "payout": str(yes_ticket["payout"]),
                "user": yes_ticket["user"],
                "salt": yes_ticket["salt"],
                "leaf": yes_ticket["leaf"],
                "leaf_int": str(yes_ticket["leaf_int"]),
            },
            {
                "ticket_id": no_ticket["ticket_id"],
                "outcome_id": no_ticket["outcome_id"],
                "amount": str(no_ticket["amount"]),
                "payout": str(no_ticket["payout"]),
                "user": no_ticket["user"],
                "salt": no_ticket["salt"],
                "leaf": no_ticket["leaf"],
                "leaf_int": str(no_ticket["leaf_int"]),
            },
        ],
        rake_bps=rake_bps,
        phase3_complete=True,
    )

    if all_ok:
        log.info("")
        log.info("Phase 3 COMPLETE - 2 bets placed (YES + NO).")
    else:
        log.error("Phase 3 FAILED - Some checks did not pass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
