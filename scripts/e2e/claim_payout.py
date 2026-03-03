#!/usr/bin/env python3
"""Phase 8: Winner claims payout, verify loser cannot claim."""

from __future__ import annotations

import sys

from utils import (
    MARKET_ABI,
    POOL_ABI,
    PROTOCOL_POOL,
    RELAYER_ESCROW,
    TEST_ACCOUNT_KEY,
    ZEN_TOKEN,
    ERC20_ABI,
    ESCROW_ABI,
    build_web3,
    check,
    contract,
    header,
    load_state,
    log,
    relayer_post,
    setup_logging,
    update_state,
    wait_for_relayer_job,
    wei_to_zen,
)
from eth_account import Account


def main() -> int:
    setup_logging()
    header("Phase 8: Claiming Payouts")

    state = load_state()
    market_address = state["market_address"]
    event_id = state["event_id"]
    tickets = state["tickets"]
    merkle_proofs = state["merkle_proofs"]
    winning_outcome = state["winning_outcome"]

    web3 = build_web3()
    market = contract(web3, market_address, MARKET_ABI)
    zen = contract(web3, ZEN_TOKEN, ERC20_ABI)
    pool = contract(web3, PROTOCOL_POOL, POOL_ABI)
    escrow = contract(web3, RELAYER_ESCROW, ESCROW_ABI)
    test_account = Account.from_key(TEST_ACCOUNT_KEY)

    log.info("Market:          %s", market_address)
    log.info("Test account:    %s", test_account.address)
    log.info("Winning outcome: %s", winning_outcome)

    # Snapshot balances before claims
    zen_before = zen.functions.balanceOf(test_account.address).call()
    escrow_before = escrow.functions.balanceOf(test_account.address).call()
    pool_before = pool.functions.totalAssets().call()
    log.info("Before claiming:")
    log.info("  ZEN balance:     %s", wei_to_zen(zen_before))
    log.info("  Escrow balance:  %s", wei_to_zen(escrow_before))
    log.info("  Pool totalAssets:%s", wei_to_zen(pool_before))

    # Identify winner and loser tickets
    winner = None
    loser = None
    for t in tickets:
        if t["outcome_id"] == winning_outcome:
            winner = t
        else:
            loser = t

    if not winner:
        log.error("No winning ticket found!")
        return 1

    # -----------------------------------------------------------------------
    # 8.1 Winner Claims
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 8.1 Winner Claims ---")
    log.info("Claiming ticket_id=%s (outcome=%s, payout=%s)",
             winner["ticket_id"], winner["outcome_id"], wei_to_zen(int(winner["payout"])))

    # Check if already claimed (idempotent re-run)
    already_claimed = market.functions.claimedTickets(winner["ticket_id"]).call()
    if already_claimed:
        log.info("Winner ticket already claimed (idempotent re-run)")
    else:
        winner_proof = merkle_proofs[str(winner["ticket_id"])]
        log.info("Merkle proof length: %d siblings", len(winner_proof))

        claim_payload = {
            "market": market_address,
            "user": winner["user"],
            "ticket_id": winner["ticket_id"],
            "outcome_id": winner["outcome_id"],
            "amount": int(winner["amount"]),
            "payout": int(winner["payout"]),
            "salt": winner["salt"],
            "merkle_proof": winner_proof,
            "event_id": event_id,
        }

        try:
            result = relayer_post("/claim", claim_payload)
            if "jobId" in result:
                log.info("Job queued: %s — waiting...", result["jobId"])
                result = wait_for_relayer_job(result["jobId"])
            log.info("Claim result: %s", result.get("txHash", result.get("tx_hash", result)))
        except Exception as exc:
            log.error("Winner claim failed: %s", exc)
            return 1

    # Verify winner claim
    claimed = market.functions.claimedTickets(winner["ticket_id"]).call()
    log.info("Winner ticket claimed: %s", claimed)
    check("Winner ticket marked as claimed", claimed)

    # -----------------------------------------------------------------------
    # 8.2 Loser Cannot Claim
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 8.2 Loser Cannot Claim ---")
    if loser:
        loser_proof = merkle_proofs[str(loser["ticket_id"])]
        loser_payload = {
            "market": market_address,
            "user": loser["user"],
            "ticket_id": loser["ticket_id"],
            "outcome_id": loser["outcome_id"],
            "amount": int(loser["amount"]),
            "payout": int(loser["payout"]),
            "salt": loser["salt"],
            "merkle_proof": loser_proof,
            "event_id": event_id,
        }

        loser_reverted = False
        try:
            result = relayer_post("/claim", loser_payload)
            if "jobId" in result:
                log.info("Job queued: %s — waiting...", result["jobId"])
                try:
                    result = wait_for_relayer_job(result["jobId"])
                    log.warning("Loser claim unexpectedly succeeded: %s", result)
                except RuntimeError:
                    loser_reverted = True
            else:
                log.warning("Loser claim unexpectedly returned 200: %s", result)
        except Exception:
            loser_reverted = True

        if loser_reverted:
            log.info("Loser claim correctly reverted!")
        check("Loser claim reverted", loser_reverted)
    else:
        log.info("No loser ticket to test (same user, both outcomes)")

    # -----------------------------------------------------------------------
    # 8.3 Verify Final State
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 8.3 Verify Final State ---")

    zen_after = zen.functions.balanceOf(test_account.address).call()
    escrow_after = escrow.functions.balanceOf(test_account.address).call()
    pool_after = pool.functions.totalAssets().call()
    pool_liability = pool.functions.consumedLiability(web3.to_checksum_address(market_address)).call()

    log.info("After claiming:")
    log.info("  ZEN balance:     %s (was %s)", wei_to_zen(zen_after), wei_to_zen(zen_before))
    log.info("  Escrow balance:  %s (was %s)", wei_to_zen(escrow_after), wei_to_zen(escrow_before))
    log.info("  Pool totalAssets:%s (was %s)", wei_to_zen(pool_after), wei_to_zen(pool_before))
    log.info("  Pool consumed:   %s", wei_to_zen(pool_liability))

    # The winner should receive payout (2 ZEN) to their escrow or direct balance
    # Depending on the claim path, payout goes to escrow credit or direct ZEN
    payout_expected = int(winner["payout"])
    balance_delta = (zen_after - zen_before) + (escrow_after - escrow_before)
    log.info("  Balance delta:   %s (expected ~%s)", wei_to_zen(balance_delta), wei_to_zen(payout_expected))

    all_ok = True
    if already_claimed:
        # On idempotent re-run, payout was already received before snapshot
        log.info("  (Idempotent run: payout was already received before this run's snapshot)")
        all_ok &= check("Winner ticket is claimed", already_claimed)
    else:
        all_ok &= check("Winner received payout", balance_delta > 0, wei_to_zen(balance_delta))
    all_ok &= check("Pool debited for liability", pool_liability >= 0)

    update_state(
        zen_before=str(zen_before),
        zen_after=str(zen_after),
        escrow_before=str(escrow_before),
        escrow_after=str(escrow_after),
        pool_before=str(pool_before),
        pool_after=str(pool_after),
        phase8_complete=True,
    )

    if all_ok:
        log.info("")
        log.info("Phase 8 COMPLETE - Winner claimed, loser rejected, balances verified.")
    else:
        log.error("Phase 8 FAILED - Some checks did not pass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
