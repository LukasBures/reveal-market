#!/usr/bin/env python3
"""Phase 1: Fund Protocol Pool, RelayerEscrow, and key accounts with ZEN."""

from __future__ import annotations

import sys

from eth_account import Account
from utils import (
    DEPLOYER_KEY,
    ERC20_ABI,
    ESCROW_ABI,
    FUNDING_WALLET_KEY,
    POOL_ABI,
    PROTOCOL_POOL,
    RELAYER_ESCROW,
    TEST_ACCOUNT_KEY,
    ZEN_TOKEN,
    build_web3,
    check,
    contract,
    header,
    log,
    send_tx,
    setup_logging,
    update_state,
    wei_to_zen,
)

# Amounts in wei (18 decimals)
ZEN_TO_DEPLOYER = 15 * 10**18  # 15 ZEN for pool deposit + gas
ZEN_TO_TEST = 5 * 10**18  # 5 ZEN for betting via escrow
POOL_DEPOSIT = 10 * 10**18  # 10 ZEN LP deposit
ESCROW_DEPOSIT = 5 * 10**18  # 5 ZEN escrow deposit (covers 2×1 ZEN tickets + buffer)


def main() -> int:
    setup_logging()
    header("Phase 1: Funding & Setup")

    web3 = build_web3()
    zen = contract(web3, ZEN_TOKEN, ERC20_ABI)
    pool = contract(web3, PROTOCOL_POOL, POOL_ABI)
    escrow = contract(web3, RELAYER_ESCROW, ESCROW_ABI)

    funding_account = Account.from_key(FUNDING_WALLET_KEY)
    deployer_account = Account.from_key(DEPLOYER_KEY)
    test_account = Account.from_key(TEST_ACCOUNT_KEY)

    log.info("Funding wallet:  %s", funding_account.address)
    log.info("Deployer:        %s", deployer_account.address)
    log.info("Test account:    %s", test_account.address)

    # Check initial balances
    funding_bal = zen.functions.balanceOf(funding_account.address).call()
    log.info("Funding wallet ZEN: %s", wei_to_zen(funding_bal))

    needed = ZEN_TO_DEPLOYER + ZEN_TO_TEST
    if funding_bal < needed:
        log.error("Insufficient funding wallet balance: have %s, need %s", wei_to_zen(funding_bal), wei_to_zen(needed))
        return 1

    # -----------------------------------------------------------------------
    # 1.1 Transfer ZEN from Funding Wallet to Deployer
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 1.1 Transfer ZEN to Deployer ---")
    deployer_bal = zen.functions.balanceOf(deployer_account.address).call()
    if deployer_bal >= ZEN_TO_DEPLOYER:
        log.info("Deployer already has %s, skipping transfer", wei_to_zen(deployer_bal))
    else:
        send_tx(
            web3,
            FUNDING_WALLET_KEY,
            zen.functions.transfer(deployer_account.address, ZEN_TO_DEPLOYER),
            label="transfer-to-deployer",
        )

    # -----------------------------------------------------------------------
    # 1.1b Transfer ZEN from Funding Wallet to Test Account
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 1.1b Transfer ZEN to Test Account ---")
    test_bal = zen.functions.balanceOf(test_account.address).call()
    if test_bal >= ZEN_TO_TEST:
        log.info("Test account already has %s, skipping transfer", wei_to_zen(test_bal))
    else:
        send_tx(
            web3,
            FUNDING_WALLET_KEY,
            zen.functions.transfer(test_account.address, ZEN_TO_TEST),
            label="transfer-to-test",
        )

    # -----------------------------------------------------------------------
    # 1.2 Deployer deposits into Protocol Pool
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 1.2 Fund Protocol Pool (LP Deposit) ---")
    pool_assets = pool.functions.totalAssets().call()
    if pool_assets >= POOL_DEPOSIT:
        log.info("Pool already has %s totalAssets, skipping deposit", wei_to_zen(pool_assets))
    else:
        # Approve
        allowance = zen.functions.allowance(deployer_account.address, web3.to_checksum_address(PROTOCOL_POOL)).call()
        if allowance < POOL_DEPOSIT:
            send_tx(
                web3,
                DEPLOYER_KEY,
                zen.functions.approve(web3.to_checksum_address(PROTOCOL_POOL), POOL_DEPOSIT),
                label="approve-pool",
            )
        # Deposit
        send_tx(
            web3,
            DEPLOYER_KEY,
            pool.functions.deposit(POOL_DEPOSIT),
            label="deposit-pool",
        )

    # -----------------------------------------------------------------------
    # 1.3 Test user deposits into Relayer Escrow
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 1.3 Fund Relayer Escrow for Test User ---")
    escrow_bal = escrow.functions.balanceOf(test_account.address).call()
    if escrow_bal >= ESCROW_DEPOSIT:
        log.info("Test user escrow already has %s, skipping deposit", wei_to_zen(escrow_bal))
    else:
        # Approve
        allowance = zen.functions.allowance(test_account.address, web3.to_checksum_address(RELAYER_ESCROW)).call()
        if allowance < ESCROW_DEPOSIT:
            send_tx(
                web3,
                TEST_ACCOUNT_KEY,
                zen.functions.approve(web3.to_checksum_address(RELAYER_ESCROW), ESCROW_DEPOSIT),
                label="approve-escrow",
            )
        # Deposit
        send_tx(
            web3,
            TEST_ACCOUNT_KEY,
            escrow.functions.deposit(ESCROW_DEPOSIT),
            label="deposit-escrow",
        )

    # -----------------------------------------------------------------------
    # 1.4 Verify Balances
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 1.4 Verify Balances ---")
    pool_total = pool.functions.totalAssets().call()
    pool_idle = pool.functions.idleLiquidity().call()
    escrow_bal = escrow.functions.balanceOf(test_account.address).call()
    deployer_bal = zen.functions.balanceOf(deployer_account.address).call()
    test_bal = zen.functions.balanceOf(test_account.address).call()

    log.info("Pool totalAssets:    %s", wei_to_zen(pool_total))
    log.info("Pool idleLiquidity:  %s", wei_to_zen(pool_idle))
    log.info("Escrow balance:      %s", wei_to_zen(escrow_bal))
    log.info("Deployer ZEN:        %s", wei_to_zen(deployer_bal))
    log.info("Test account ZEN:    %s", wei_to_zen(test_bal))

    all_ok = True
    all_ok &= check("Pool totalAssets > 0", pool_total > 0, wei_to_zen(pool_total))
    all_ok &= check("Pool idleLiquidity > 0", pool_idle > 0, wei_to_zen(pool_idle))
    all_ok &= check("Escrow balance > 0", escrow_bal > 0, wei_to_zen(escrow_bal))

    # Save state
    update_state(
        pool_total_assets=str(pool_total),
        pool_idle_liquidity=str(pool_idle),
        escrow_balance=str(escrow_bal),
        test_account=test_account.address,
        deployer_account=deployer_account.address,
        phase1_complete=True,
    )

    if all_ok:
        log.info("")
        log.info("Phase 1 COMPLETE - All accounts funded.")
    else:
        log.error("Phase 1 FAILED - Some checks did not pass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
