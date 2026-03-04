#!/usr/bin/env python3
"""Phase 2: Create a market on-chain via MarketFactory and register in the database."""

from __future__ import annotations

import sys
import time
from datetime import UTC

from eth_account import Account
from utils import (
    AUTH_SIGNER_ADDRESS,
    CIRCUIT_HASH,
    DEPLOYER_KEY,
    FACTORY,
    FACTORY_ABI,
    MARKET_ABI,
    ORACLE_ADDRESS,
    VERIFIER,
    api_post,
    build_web3,
    check,
    contract,
    header,
    log,
    phase_name,
    send_tx,
    setup_logging,
    update_state,
    wei_to_zen,
)

# Market parameters
COMMIT_DEADLINE_OFFSET = 300  # 5 minutes from now (short for E2E test)
TICKET_SIZE = 1 * 10**18  # 1 ZEN
MAX_COMMITMENTS = 256  # 1 batch
LIABILITY_CAP = 5 * 10**18  # 5 ZEN (must fit within pool balance of 10 ZEN)


def main() -> int:
    setup_logging()
    header("Phase 2: Market Creation")

    web3 = build_web3()
    factory = contract(web3, FACTORY, FACTORY_ABI)

    deployer = Account.from_key(DEPLOYER_KEY)
    log.info("Deployer: %s", deployer.address)

    # Check nextMarketId before creation
    next_id_before = factory.functions.nextMarketId().call()
    log.info("Factory nextMarketId (before): %s", next_id_before)

    # -----------------------------------------------------------------------
    # 2.0 Approve Verifier (if not already approved)
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 2.0 Approve Verifier ---")
    verifier_addr = web3.to_checksum_address(VERIFIER)
    try:
        is_approved = factory.functions.approvedVerifiers(verifier_addr).call()
    except Exception:
        is_approved = False

    if is_approved:
        log.info("Verifier %s already approved", verifier_addr)
    else:
        log.info("Approving verifier %s...", verifier_addr)
        send_tx(
            web3,
            DEPLOYER_KEY,
            factory.functions.setVerifierApproval(verifier_addr, True),
            label="approve-verifier",
        )
        log.info("Verifier approved!")

    # -----------------------------------------------------------------------
    # 2.1 Create Market On-Chain
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 2.1 Create Market On-Chain ---")

    commit_deadline = int(time.time()) + COMMIT_DEADLINE_OFFSET
    circuit_hash_bytes = bytes.fromhex(CIRCUIT_HASH[2:] if CIRCUIT_HASH.startswith("0x") else CIRCUIT_HASH)

    create_params = (
        web3.to_checksum_address(ORACLE_ADDRESS),  # oracle
        web3.to_checksum_address(VERIFIER),  # verifier
        circuit_hash_bytes,  # circuitHash
        commit_deadline,  # commitDeadline
        TICKET_SIZE,  # fixedTicketSize
        MAX_COMMITMENTS,  # maxCommitments
        web3.to_checksum_address(AUTH_SIGNER_ADDRESS),  # authorizationSigner
        LIABILITY_CAP,  # protocolLiabilityCap
    )

    log.info("CreateMarket params:")
    log.info("  oracle:             %s", ORACLE_ADDRESS)
    log.info("  verifier:           %s", VERIFIER)
    log.info("  circuitHash:        %s", CIRCUIT_HASH)
    log.info("  commitDeadline:     %s (now + %ds)", commit_deadline, COMMIT_DEADLINE_OFFSET)
    log.info("  fixedTicketSize:    %s", wei_to_zen(TICKET_SIZE))
    log.info("  maxCommitments:     %s", MAX_COMMITMENTS)
    log.info("  authorizationSigner:%s", AUTH_SIGNER_ADDRESS)
    log.info("  liabilityCap:       %s", wei_to_zen(LIABILITY_CAP))

    send_tx(
        web3,
        DEPLOYER_KEY,
        factory.functions.createMarket(create_params),
        label="create-market",
    )

    # Extract market address from logs (MarketCreated event) or use nextMarketId
    next_id_after = factory.functions.nextMarketId().call()
    market_id = next_id_after - 1
    market_address = factory.functions.marketAddress(market_id).call()
    log.info("Market created!")
    log.info("  marketId:      %s", market_id)
    log.info("  marketAddress:  %s", market_address)

    # Read and log rake for visibility
    market = contract(web3, market_address, MARKET_ABI)
    on_chain_rake = market.functions.rakeBps().call()
    log.info("  rakeBps:       %s (%s%%)", on_chain_rake, on_chain_rake / 100)

    # -----------------------------------------------------------------------
    # 2.2 Register Market in Database
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 2.2 Register Market in Database ---")

    from datetime import datetime

    closes_at = datetime.fromtimestamp(commit_deadline, tz=UTC).isoformat()
    event_id = f"e2e-test-{market_id}-{int(time.time())}"

    market_data = {
        "event_id": event_id,
        "title": "E2E Test Market: Will the integration test pass?",
        "category": "test",
        "oracle": web3.to_checksum_address(ORACLE_ADDRESS),
        "market_address": market_address,
        "onchain_market_id": market_id,
        "factory": web3.to_checksum_address(FACTORY),
        "status": "commit",
        "closes_at": closes_at,
        "outcomes": ["Yes", "No"],
        "outcome_prices": [0.5, 0.5],
    }

    log.info("Registering market in DB: event_id=%s", event_id)
    try:
        resp = api_post("/events", market_data)
        log.info("DB registration response: %s", resp.get("event_id", resp))
    except Exception as exc:
        log.warning("DB registration failed (may need manual insert): %s", exc)
        log.info("Continuing anyway - on-chain state is the source of truth for this test")

    # -----------------------------------------------------------------------
    # 2.3 Verify Market On-Chain
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 2.3 Verify Market On-Chain ---")

    market = contract(web3, market_address, MARKET_ABI)
    on_phase = market.functions.phase().call()
    on_ticket_size = market.functions.ticketSize().call()
    on_next_ticket = market.functions.nextTicketId().call()
    on_deadline = market.functions.commitDeadline().call()
    on_market_id = market.functions.marketId().call()
    on_oracle = market.functions.oracle().call()
    on_max = market.functions.maxCommitments().call()

    log.info("  phase:           %s (%s)", on_phase, phase_name(on_phase))
    log.info("  ticketSize:      %s", wei_to_zen(on_ticket_size))
    log.info("  nextTicketId:    %s", on_next_ticket)
    log.info("  commitDeadline:  %s", on_deadline)
    log.info("  marketId:        %s", on_market_id)
    log.info("  oracle:          %s", on_oracle)
    log.info("  maxCommitments:  %s", on_max)

    all_ok = True
    all_ok &= check("Phase is Commit (0)", on_phase == 0, f"got {on_phase}")
    all_ok &= check("Ticket size is 1 ZEN", on_ticket_size == TICKET_SIZE)
    all_ok &= check("nextTicketId is 0", on_next_ticket == 0)
    all_ok &= check("marketId matches", on_market_id == market_id)
    all_ok &= check("Oracle matches", on_oracle.lower() == ORACLE_ADDRESS.lower())
    all_ok &= check("maxCommitments is 256", on_max == MAX_COMMITMENTS)

    # Save state for next phases
    update_state(
        market_address=market_address,
        market_id=market_id,
        event_id=event_id,
        commit_deadline=commit_deadline,
        ticket_size=str(TICKET_SIZE),
        max_commitments=MAX_COMMITMENTS,
        phase2_complete=True,
    )

    if all_ok:
        log.info("")
        log.info("Phase 2 COMPLETE - Market deployed at %s (id=%s)", market_address, market_id)
    else:
        log.error("Phase 2 FAILED - Some checks did not pass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
