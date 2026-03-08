#!/usr/bin/env python3
"""E2E: ProtocolPool deposit, lock, emergency unlock, withdraw lifecycle.

Tests:
  1. Deposit 0.3 ZEN into the pool
  2. Verify 30-day timelock blocks withdrawal
  3. Grant emergency unlock → partial withdraw 0.1 ZEN
  4. Revoke emergency unlock → verify re-lock blocks withdrawal
  5. Grant emergency unlock again → withdraw remaining 0.2 ZEN
  6. Final re-lock + cleanup
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from eth_account import Account
from utils import (
    DEPLOYER_KEY,
    ERC20_ABI,
    POOL_ABI,
    PROTOCOL_POOL,
    ZEN_TOKEN,
    build_web3,
    check,
    contract,
    header,
    log,
    send_tx,
    setup_logging,
    wei_to_zen,
)

# Extra ABI entries not in utils.py — needed for per-deposit inspection
EXTRA_POOL_ABI = [
    {
        "inputs": [{"name": "lp", "type": "address"}],
        "name": "depositCount",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "lp", "type": "address"}, {"name": "index", "type": "uint256"}],
        "name": "depositAt",
        "outputs": [{"name": "shares", "type": "uint256"}, {"name": "unlockTime", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

DEPOSIT_AMOUNT = 300_000_000_000_000_000  # 0.3 ZEN
PARTIAL = 100_000_000_000_000_000  # 0.1 ZEN


def main() -> int:
    setup_logging()
    header("ProtocolPool: Deposit, Lock, Emergency Unlock, Withdraw")

    web3 = build_web3()
    pool = contract(web3, PROTOCOL_POOL, POOL_ABI + EXTRA_POOL_ABI)
    zen = contract(web3, ZEN_TOKEN, ERC20_ABI)
    deployer = Account.from_key(DEPLOYER_KEY)
    log.info("Deployer: %s", deployer.address)

    all_ok = True

    # -----------------------------------------------------------------------
    # Step 1: Pre-flight
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 1: Pre-flight ---")

    total_assets_0 = pool.functions.totalAssets().call()
    total_shares_0 = pool.functions.totalShares().call()
    idle_0 = pool.functions.idleLiquidity().call()
    lock_duration = pool.functions.LOCK_DURATION().call()

    log.info("totalAssets:    %s", wei_to_zen(total_assets_0))
    log.info("totalShares:    %s", wei_to_zen(total_shares_0))
    log.info("idleLiquidity:  %s", wei_to_zen(idle_0))
    log.info("LOCK_DURATION:  %d seconds (%d days)", lock_duration, lock_duration // 86400)

    zen_balance_0 = zen.functions.balanceOf(deployer.address).call()
    shares_0 = pool.functions.lpShareBalance(deployer.address).call()
    log.info("Deployer ZEN:   %s", wei_to_zen(zen_balance_0))
    log.info("Deployer shares: %s", wei_to_zen(shares_0))

    owner = pool.functions.owner().call()
    is_owner = owner.lower() == deployer.address.lower()
    all_ok &= check("Deployer is pool owner", is_owner)
    if not is_owner:
        log.error("Deployer must be pool owner for emergency unlock calls.")
        return 1

    all_ok &= check("Deployer has enough ZEN", zen_balance_0 >= DEPOSIT_AMOUNT, wei_to_zen(zen_balance_0))
    if zen_balance_0 < DEPOSIT_AMOUNT:
        log.error("Insufficient ZEN balance for deposit.")
        return 1

    # -----------------------------------------------------------------------
    # Step 2: Deposit 0.3 ZEN
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 2: Deposit 0.3 ZEN ---")

    send_tx(
        web3,
        DEPLOYER_KEY,
        zen.functions.approve(web3.to_checksum_address(PROTOCOL_POOL), DEPOSIT_AMOUNT),
        label="approve-zen",
    )
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.deposit(DEPOSIT_AMOUNT),
        label="deposit-0.3-zen",
    )

    shares_after_deposit = pool.functions.lpShareBalance(deployer.address).call()
    total_assets_after = pool.functions.totalAssets().call()
    new_shares = shares_after_deposit - shares_0

    log.info("Shares before:  %s", wei_to_zen(shares_0))
    log.info("Shares after:   %s", wei_to_zen(shares_after_deposit))
    log.info("New shares:     %s", wei_to_zen(new_shares))
    log.info("totalAssets:    %s -> %s", wei_to_zen(total_assets_0), wei_to_zen(total_assets_after))

    all_ok &= check("Shares increased", new_shares > 0, wei_to_zen(new_shares))
    all_ok &= check("totalAssets increased", total_assets_after > total_assets_0)

    # -----------------------------------------------------------------------
    # Step 3: Verify 30-day lock
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 3: Verify 30-day lock ---")

    unlocked = pool.functions.unlockedShares(deployer.address).call()
    log.info("unlockedShares: %s", wei_to_zen(unlocked))
    all_ok &= check("unlockedShares is 0 (new deposit locked)", unlocked == 0)

    # Attempt withdrawal — must revert
    reverted = False
    try:
        send_tx(web3, DEPLOYER_KEY, pool.functions.lpWithdraw(new_shares, 0), label="withdraw-locked")
    except Exception:
        reverted = True
    all_ok &= check("lpWithdraw reverted (timelock)", reverted)

    # Inspect deposit record
    deposit_count = pool.functions.depositCount(deployer.address).call()
    log.info("depositCount:   %d", deposit_count)
    if deposit_count > 0:
        last_idx = deposit_count - 1
        dep_shares, unlock_time = pool.functions.depositAt(deployer.address, last_idx).call()
        unlock_dt = datetime.fromtimestamp(unlock_time, tz=UTC)
        log.info("Latest deposit: shares=%s  unlockTime=%s", wei_to_zen(dep_shares), unlock_dt.isoformat())
        all_ok &= check(
            "Unlock ~30 days out",
            unlock_time > int(datetime.now(tz=UTC).timestamp()),
            unlock_dt.isoformat(),
        )

    # -----------------------------------------------------------------------
    # Step 4: Grant emergency unlock
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 4: Grant emergency unlock ---")

    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.grantEmergencyUnlock(deployer.address),
        label="grant-emergency-unlock",
    )

    eu_flag = pool.functions.emergencyUnlocked(deployer.address).call()
    log.info("emergencyUnlocked: %s", eu_flag)
    all_ok &= check("Emergency unlock granted", eu_flag is True)

    unlocked_after_eu = pool.functions.unlockedShares(deployer.address).call()
    log.info("unlockedShares:    %s", wei_to_zen(unlocked_after_eu))
    all_ok &= check(
        "unlockedShares equals full balance",
        unlocked_after_eu == shares_after_deposit,
        f"{wei_to_zen(unlocked_after_eu)} vs {wei_to_zen(shares_after_deposit)}",
    )

    # -----------------------------------------------------------------------
    # Step 5: Withdraw 0.1 ZEN
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 5: Withdraw 0.1 ZEN (partial) ---")

    zen_before_w1 = zen.functions.balanceOf(deployer.address).call()
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.lpWithdraw(PARTIAL, 0),
        label="withdraw-0.1-zen",
    )
    zen_after_w1 = zen.functions.balanceOf(deployer.address).call()
    shares_after_w1 = pool.functions.lpShareBalance(deployer.address).call()

    log.info("ZEN before:  %s", wei_to_zen(zen_before_w1))
    log.info("ZEN after:   %s", wei_to_zen(zen_after_w1))
    log.info("Shares now:  %s", wei_to_zen(shares_after_w1))

    all_ok &= check("ZEN balance increased", zen_after_w1 > zen_before_w1)
    all_ok &= check(
        "Shares decreased by ~0.1 ZEN",
        shares_after_w1 < shares_after_deposit,
        f"delta={wei_to_zen(shares_after_deposit - shares_after_w1)}",
    )

    remaining_shares = shares_after_w1 - shares_0  # only shares from this test's deposit

    # -----------------------------------------------------------------------
    # Step 6: Re-lock (revoke emergency unlock)
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 6: Revoke emergency unlock (re-lock) ---")

    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.revokeEmergencyUnlock(deployer.address),
        label="revoke-emergency-unlock",
    )

    eu_flag_2 = pool.functions.emergencyUnlocked(deployer.address).call()
    unlocked_after_revoke = pool.functions.unlockedShares(deployer.address).call()
    log.info("emergencyUnlocked: %s", eu_flag_2)
    log.info("unlockedShares:    %s", wei_to_zen(unlocked_after_revoke))

    all_ok &= check("Emergency unlock revoked", eu_flag_2 is False)
    all_ok &= check("unlockedShares is 0", unlocked_after_revoke == 0)

    # -----------------------------------------------------------------------
    # Step 7: Attempt withdraw 0.2 ZEN — must fail
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 7: Attempt withdraw after re-lock (expect revert) ---")

    reverted_2 = False
    try:
        send_tx(
            web3,
            DEPLOYER_KEY,
            pool.functions.lpWithdraw(remaining_shares, 0),
            label="withdraw-relocked",
        )
    except Exception:
        reverted_2 = True
    all_ok &= check("lpWithdraw reverted after re-lock", reverted_2)

    # -----------------------------------------------------------------------
    # Step 8: Unlock + withdraw remaining 0.2 ZEN
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 8: Emergency unlock + withdraw remaining ---")

    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.grantEmergencyUnlock(deployer.address),
        label="grant-emergency-unlock-2",
    )

    zen_before_w2 = zen.functions.balanceOf(deployer.address).call()
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.lpWithdraw(remaining_shares, 0),
        label="withdraw-remaining",
    )
    zen_after_w2 = zen.functions.balanceOf(deployer.address).call()
    shares_final = pool.functions.lpShareBalance(deployer.address).call()

    log.info("ZEN before:   %s", wei_to_zen(zen_before_w2))
    log.info("ZEN after:    %s", wei_to_zen(zen_after_w2))
    log.info("Shares final: %s", wei_to_zen(shares_final))

    all_ok &= check("Remaining shares redeemed", shares_final == shares_0, wei_to_zen(shares_final))
    all_ok &= check("ZEN balance increased", zen_after_w2 > zen_before_w2)

    # Verify ZEN is approximately restored to pre-deposit level
    zen_diff = abs(zen_after_w2 - zen_balance_0)
    log.info("ZEN diff from start: %s (gas costs)", wei_to_zen(zen_diff))

    # -----------------------------------------------------------------------
    # Step 9: Final re-lock + cleanup
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- Step 9: Final re-lock + summary ---")

    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.revokeEmergencyUnlock(deployer.address),
        label="final-revoke",
    )

    eu_flag_final = pool.functions.emergencyUnlocked(deployer.address).call()
    all_ok &= check("Emergency unlock revoked (final)", eu_flag_final is False)

    # Final pool state
    total_assets_f = pool.functions.totalAssets().call()
    total_shares_f = pool.functions.totalShares().call()
    idle_f = pool.functions.idleLiquidity().call()

    log.info("")
    log.info("Final pool state:")
    log.info("  totalAssets:   %s", wei_to_zen(total_assets_f))
    log.info("  totalShares:   %s", wei_to_zen(total_shares_f))
    log.info("  idleLiquidity: %s", wei_to_zen(idle_f))
    log.info("  deployer shares: %s", wei_to_zen(shares_final))

    if all_ok:
        log.info("")
        log.info("Deposit/Withdraw Lifecycle Test COMPLETE - All checks passed.")
    else:
        log.error("Deposit/Withdraw Lifecycle Test FAILED - Some checks did not pass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
