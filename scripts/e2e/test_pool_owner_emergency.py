#!/usr/bin/env python3
"""E2E: Test ProtocolPool owner emergency functions.

Tests:
  1. setDrawsPaused — toggle global draw pause
  2. Owner withdraw — extract surplus (or verify revert when none)
  3. forceReleaseLiability — release stuck market reservations
"""

from __future__ import annotations

import sys

from eth_account import Account
from utils import (
    DEPLOYER_KEY,
    POOL_ABI,
    PROTOCOL_POOL,
    build_web3,
    check,
    contract,
    header,
    load_state,
    log,
    send_tx,
    setup_logging,
    update_state,
    wei_to_zen,
)


def main() -> int:
    setup_logging()
    header("ProtocolPool: Owner Emergency Functions Test")

    web3 = build_web3()
    pool = contract(web3, PROTOCOL_POOL, POOL_ABI)
    deployer = Account.from_key(DEPLOYER_KEY)
    log.info("Deployer: %s", deployer.address)

    # -----------------------------------------------------------------------
    # 1. Verify deployer is owner
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 1. Verify Ownership ---")
    owner = pool.functions.owner().call()
    log.info("Pool owner:  %s", owner)
    log.info("Deployer:    %s", deployer.address)

    all_ok = True
    is_owner = owner.lower() == deployer.address.lower()
    all_ok &= check("Deployer is pool owner", is_owner)

    if not is_owner:
        log.error("Deployer is not the pool owner. Cannot test owner functions.")
        return 1

    # -----------------------------------------------------------------------
    # 2. Pool state snapshot
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 2. Pool State ---")
    total_assets = pool.functions.totalAssets().call()
    total_shares = pool.functions.totalShares().call()
    reserved = pool.functions.reservedTotal().call()
    idle = pool.functions.idleLiquidity().call()
    draws_paused = pool.functions.drawsPaused().call()

    log.info("totalAssets:    %s", wei_to_zen(total_assets))
    log.info("totalShares:    %s", wei_to_zen(total_shares))
    log.info("reservedTotal:  %s", wei_to_zen(reserved))
    log.info("idleLiquidity:  %s", wei_to_zen(idle))
    log.info("drawsPaused:    %s", draws_paused)

    floor = max(reserved, total_shares)
    surplus = total_assets - floor if total_assets > floor else 0
    log.info("Surplus (owner-withdrawable): %s", wei_to_zen(surplus))

    # -----------------------------------------------------------------------
    # 3. Test setDrawsPaused
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 3. Test setDrawsPaused ---")

    # Pause draws
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.setDrawsPaused(True),
        label="pause-draws",
    )
    paused_state = pool.functions.drawsPaused().call()
    log.info("drawsPaused after pause: %s", paused_state)
    all_ok &= check("Draws paused", paused_state is True)

    # Unpause draws
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.setDrawsPaused(False),
        label="unpause-draws",
    )
    unpaused_state = pool.functions.drawsPaused().call()
    log.info("drawsPaused after unpause: %s", unpaused_state)
    all_ok &= check("Draws unpaused", unpaused_state is False)

    # -----------------------------------------------------------------------
    # 4. Test owner withdraw (surplus only)
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 4. Test Owner Withdraw ---")

    if surplus > 0:
        # Withdraw 1 wei of surplus
        log.info("Surplus available, withdrawing 1 wei...")
        send_tx(
            web3,
            DEPLOYER_KEY,
            pool.functions.withdraw(deployer.address, 1),
            label="owner-withdraw-1wei",
        )
        new_assets = pool.functions.totalAssets().call()
        all_ok &= check(
            "Owner withdraw reduced totalAssets",
            new_assets < total_assets,
            f"{wei_to_zen(total_assets)} -> {wei_to_zen(new_assets)}",
        )
    else:
        # No surplus — withdraw should revert
        log.info("No surplus available, expecting revert...")
        withdraw_reverted = False
        revert_reason = ""
        try:
            send_tx(
                web3,
                DEPLOYER_KEY,
                pool.functions.withdraw(deployer.address, 1),
                label="owner-withdraw-no-surplus",
            )
            log.warning("Owner withdraw unexpectedly succeeded with no surplus!")
        except Exception as exc:
            withdraw_reverted = True
            revert_reason = str(exc)
            log.info("Owner withdraw correctly reverted: %s", revert_reason)

        all_ok &= check(
            "Owner withdraw reverted (no surplus)",
            withdraw_reverted,
            revert_reason[:120] if revert_reason else "",
        )

    # -----------------------------------------------------------------------
    # 5. Test forceReleaseLiability
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 5. Test forceReleaseLiability ---")

    # Try to find a market address from E2E state
    market_address = None
    try:
        state = load_state()
        market_address = state.get("market_address")
    except FileNotFoundError:
        log.info("No e2e_state.json found, will use zero-reservation test only.")

    if market_address:
        log.info("Market from state: %s", market_address)
        market_reserved = pool.functions.reservedLiability(web3.to_checksum_address(market_address)).call()
        log.info("reservedLiability for market: %s", wei_to_zen(market_reserved))

        if market_reserved > 0:
            reserved_before = pool.functions.reservedTotal().call()
            send_tx(
                web3,
                DEPLOYER_KEY,
                pool.functions.forceReleaseLiability(web3.to_checksum_address(market_address)),
                label="force-release",
            )
            reserved_after = pool.functions.reservedTotal().call()
            all_ok &= check(
                "forceRelease reduced reservedTotal",
                reserved_after < reserved_before,
                f"{wei_to_zen(reserved_before)} -> {wei_to_zen(reserved_after)}",
            )
        else:
            # No reservation — force release should revert with InvalidAmount
            log.info("No reservation for market, expecting revert...")
            release_reverted = False
            revert_reason = ""
            try:
                send_tx(
                    web3,
                    DEPLOYER_KEY,
                    pool.functions.forceReleaseLiability(web3.to_checksum_address(market_address)),
                    label="force-release-zero",
                )
                log.warning("forceReleaseLiability unexpectedly succeeded!")
            except Exception as exc:
                release_reverted = True
                revert_reason = str(exc)
                log.info("forceReleaseLiability correctly reverted: %s", revert_reason)

            all_ok &= check(
                "forceRelease reverted (no reservation)",
                release_reverted,
                revert_reason[:120] if revert_reason else "",
            )
    else:
        # No market address — test with a dummy address
        log.info("No market address available, testing with dummy address...")
        release_reverted = False
        revert_reason = ""
        dummy = "0x0000000000000000000000000000000000000001"
        try:
            send_tx(
                web3,
                DEPLOYER_KEY,
                pool.functions.forceReleaseLiability(web3.to_checksum_address(dummy)),
                label="force-release-dummy",
            )
            log.warning("forceReleaseLiability unexpectedly succeeded!")
        except Exception as exc:
            release_reverted = True
            revert_reason = str(exc)
            log.info("forceReleaseLiability correctly reverted: %s", revert_reason)

        all_ok &= check(
            "forceRelease reverted (no reservation)",
            release_reverted,
            revert_reason[:120] if revert_reason else "",
        )

    # -----------------------------------------------------------------------
    # 6. Emergency unlock → LP withdrawal → global pause
    # -----------------------------------------------------------------------
    log.info("")
    log.info("--- 6. Emergency Unlock + LP Withdrawal + Final Pause ---")

    # Confirm draws are currently unpaused (section 3 left them off)
    pre_state = pool.functions.drawsPaused().call()
    log.info("drawsPaused (pre-step): %s", pre_state)
    if pre_state:
        send_tx(web3, DEPLOYER_KEY, pool.functions.setDrawsPaused(False), label="ensure-unpaused")
        log.info("Force-unpaused before emergency unlock test")

    # Grant emergency unlock so the deployer LP can bypass the 30-day timelock
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.grantEmergencyUnlock(deployer.address),
        label="grant-emergency-unlock",
    )
    flag = pool.functions.emergencyUnlocked(deployer.address).call()
    log.info("emergencyUnlocked[deployer]: %s", flag)
    all_ok &= check("Emergency unlock flag set", flag is True)

    # Withdraw all LP shares
    shares = pool.functions.lpShareBalance(deployer.address).call()
    unlocked = pool.functions.unlockedShares(deployer.address).call()
    log.info("lpShareBalance:  %s", wei_to_zen(shares))
    log.info("unlockedShares:  %s (should equal shares due to emergency flag)", wei_to_zen(unlocked))
    all_ok &= check("All shares unlocked via emergency flag", unlocked == shares, wei_to_zen(unlocked))

    assets_before = pool.functions.totalAssets().call()
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.lpWithdraw(shares, 0),
        label="emergency-lp-withdraw",
    )
    shares_after = pool.functions.lpShareBalance(deployer.address).call()
    assets_after = pool.functions.totalAssets().call()
    log.info("Shares after withdrawal: %s", wei_to_zen(shares_after))
    log.info("totalAssets before: %s  after: %s", wei_to_zen(assets_before), wei_to_zen(assets_after))
    all_ok &= check("All LP shares redeemed", shares_after == 0, wei_to_zen(shares_after))
    all_ok &= check("Pool assets reduced", assets_after < assets_before, wei_to_zen(assets_after))

    # Now pause draws as the final emergency action
    send_tx(
        web3,
        DEPLOYER_KEY,
        pool.functions.setDrawsPaused(True),
        label="final-pause",
    )
    final_paused = pool.functions.drawsPaused().call()
    log.info("drawsPaused (final): %s", final_paused)
    all_ok &= check("Pool draws paused after emergency withdrawal", final_paused is True)

    # -----------------------------------------------------------------------
    # Save state
    # -----------------------------------------------------------------------
    update_state(
        pool_owner_emergency_test={
            "is_owner": is_owner,
            "surplus": str(surplus),
            "draws_pause_toggle": True,
            "emergency_unlock_withdrawal": {
                "shares_withdrawn": str(shares),
                "assets_before": str(assets_before),
                "assets_after": str(assets_after),
                "final_paused": final_paused,
            },
            "all_checks_passed": all_ok,
        },
    )

    if all_ok:
        log.info("")
        log.info("Owner Emergency Functions Test COMPLETE - All checks passed.")
    else:
        log.error("Owner Emergency Functions Test FAILED - Some checks did not pass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
