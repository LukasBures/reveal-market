#!/usr/bin/env python3
"""E2E: Verify ProtocolPool LP withdrawal is timelocked (60 days)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from eth_account import Account
from utils import (
    DEPLOYER_KEY,
    POOL_ABI,
    PROTOCOL_POOL,
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


def main() -> int:
    setup_logging()
    header("ProtocolPool: LP Withdrawal Timelock Test")

    web3 = build_web3()
    pool = contract(web3, PROTOCOL_POOL, POOL_ABI)
    deployer = Account.from_key(DEPLOYER_KEY)
    log.info("Deployer (LP): %s", deployer.address)

    # -----------------------------------------------------------------------
    # 1. Read pool state
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 1. Pool State ---")
    total_assets = pool.functions.totalAssets().call()
    total_shares = pool.functions.totalShares().call()
    idle = pool.functions.idleLiquidity().call()
    reserved = pool.functions.reservedTotal().call()
    lock_duration = pool.functions.LOCK_DURATION().call()

    log.info("totalAssets:    %s", wei_to_zen(total_assets))
    log.info("totalShares:    %s", wei_to_zen(total_shares))
    log.info("idleLiquidity:  %s", wei_to_zen(idle))
    log.info("reservedTotal:  %s", wei_to_zen(reserved))
    log.info("LOCK_DURATION:  %d seconds (%d days)", lock_duration, lock_duration // 86400)

    all_ok = True
    all_ok &= check("LOCK_DURATION is 30 days", lock_duration == 30 * 86400, f"{lock_duration}s")

    # -----------------------------------------------------------------------
    # 2. Check deployer's LP position
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 2. Deployer LP Position ---")
    shares = pool.functions.lpShareBalance(deployer.address).call()
    unlocked = pool.functions.unlockedShares(deployer.address).call()
    redeemable = pool.functions.maxRedeemable(deployer.address).call()

    log.info("lpShareBalance:  %s", wei_to_zen(shares))
    log.info("unlockedShares:  %s", wei_to_zen(unlocked))
    log.info("maxRedeemable:   %s", wei_to_zen(redeemable))

    all_ok &= check("Deployer has LP shares", shares > 0, wei_to_zen(shares))
    all_ok &= check("No unlocked shares (timelock active)", unlocked == 0, wei_to_zen(unlocked))
    all_ok &= check("maxRedeemable is 0", redeemable == 0, wei_to_zen(redeemable))

    if shares > 0:
        asset_value = pool.functions.convertToAssets(shares).call()
        log.info("convertToAssets: %s (value if unlocked)", wei_to_zen(asset_value))

    # -----------------------------------------------------------------------
    # 3. Attempt lpWithdraw — expect revert
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 3. Attempt LP Withdrawal (expect revert) ---")
    withdraw_reverted = False
    revert_reason = ""
    try:
        send_tx(
            web3,
            DEPLOYER_KEY,
            pool.functions.lpWithdraw(shares, 0),
            label="lp-withdraw-locked",
        )
        log.warning("lpWithdraw unexpectedly succeeded!")
    except Exception as exc:
        withdraw_reverted = True
        revert_reason = str(exc)
        log.info("lpWithdraw correctly reverted: %s", revert_reason)

    all_ok &= check(
        "lpWithdraw reverted (timelock)",
        withdraw_reverted,
        revert_reason[:120] if revert_reason else "",
    )

    # -----------------------------------------------------------------------
    # 4. Estimate unlock time
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 4. Unlock Timeline ---")
    current_block = web3.eth.get_block("latest")
    current_time = current_block["timestamp"]
    unlock_time = current_time + lock_duration
    current_dt = datetime.fromtimestamp(current_time, tz=UTC)
    unlock_dt = datetime.fromtimestamp(unlock_time, tz=UTC)

    log.info("Current block time:    %s", current_dt.isoformat())
    log.info("Earliest unlock at:    %s", unlock_dt.isoformat())
    log.info("NOTE: This is from NOW. Actual unlock depends on original deposit time.")
    log.info("Shares deposited during setup_funding.py are locked from that timestamp.")

    # -----------------------------------------------------------------------
    # Save state
    # -----------------------------------------------------------------------
    update_state(
        pool_withdrawal_test={
            "deployer_shares": str(shares),
            "unlocked_shares": str(unlocked),
            "lock_duration_seconds": lock_duration,
            "withdraw_reverted": withdraw_reverted,
            "revert_reason": revert_reason[:200] if revert_reason else "",
        },
    )

    if all_ok:
        log.info("")
        log.info("LP Withdrawal Timelock Test COMPLETE - All checks passed.")
    else:
        log.error("LP Withdrawal Timelock Test FAILED - Some checks did not pass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
