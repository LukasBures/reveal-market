# Audit Fixes Report

Addresses 15 confirmed findings from a multi-agent security audit of `contracts/zen/src/` and `contracts/polygon/src/`.

## Findings Fixed

### 1. epsilon-H1 — BaseLpVault `withdraw()` underburns shares

**File:** `contracts/polygon/src/BaseLpVault.sol`
**Severity:** Medium
**Before:** `withdraw()` used `convertToShares(assets)` which floors via `Math.mulDiv` — user burns fewer shares than owed.
**After:** Added `_convertToSharesCeil()` using `Math.Rounding.Ceil`; `withdraw()` now calls it instead.

### 2. hyp-factory-003 / 02082bd2 / beta-c092858e — `refreshLockedVerifierKeyHash` is a no-op

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** High
**Before:** Function asserted `verifyingKeyHash == lockedVerifierKeyHash` then emitted an event — effectively a no-op that could never update the key.
**After:** Function now writes `lockedVerifierKeyHash = newKeyHash` and resets settlement progress (`currentBatchProofEpoch++`, counters zeroed) if any batch proofs were already accepted under the old key. Emits `SettlementProgressReset` when applicable.

### 3. hyp-factory-018 / hyp-factory-027 — No way to clear verifier pin after key rotation

**File:** `contracts/zen/src/MarketFactory.sol`
**Severity:** Medium
**Before:** Once a verifier was approved, its codehash + keyHash were pinned permanently. Key rotation triggered `VerifierDrift` with no recovery path.
**After:** Added `clearVerifierPin(address verifier)` — owner can clear pin after revoking approval, enabling re-approval with a new key. New error `VerifierStillApproved()` prevents clearing while approved. New event `VerifierPinCleared`.

### 4. hyp-pool-002 / hyp-pool-023 — Deposit record array grows unboundedly

**File:** `contracts/zen/src/ProtocolPool.sol`
**Severity:** Low (gas griefing)
**Before:** `_deposits[lp]` grew monotonically; zeroed-out records were never removed, increasing gas for `_unlockedSharesOf`.
**After:** Added `compactDeposits()`, `compactDepositsFor(address)`, and internal `_compactDeposits(address)`. Auto-called at end of `lpWithdraw()`.

### 5. hyp-factory-011 — `setOracle` allows Cancelled phase

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** Low
**Before:** Guard was `if (phase == Phase.Locked || phase == Phase.Settled)` — allowed oracle rotation in Cancelled phase.
**After:** Changed to `if (phase != Phase.Commit)` — oracle can only be rotated during Commit phase.

### 6. gamma-flow4-001 — Oracle claim payout ceiling

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** Medium
**Before:** `claimWithOracleAuthorization` had no per-ticket payout ceiling — a compromised oracle key could sign arbitrary payouts.
**After:** Added `if (payout > totalLiability) revert OverClaimed()` before signature validation. Added NatSpec documenting the trust assumption.

### 7. gamma-flow4-003 / hyp-claim-001 — `claimPauseTotalDuration` unbounded

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** Medium
**Before:** Pause/unpause cycles accumulated `claimPauseTotalDuration` without limit, allowing the effective claim deadline to extend indefinitely.
**After:** Capped at `MAX_CLAIM_DEADLINE_EXTENSION` (365 days) during unpause.

### 8. beta-4eba — `extendCommitDeadline` missing timestamp guard

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** Low
**Before:** `extendCommitDeadline` could be called after the commit window closed (creating a zombie extension).
**After:** Added `if (block.timestamp >= commitDeadline) revert CommitWindowClosed()`.

### 9. c3572b19 — Relayer pause silently swallows failures

**File:** `contracts/zen/src/MarketFactory.sol`
**Severity:** Medium
**Before:** `_setRelayerCommitsPausedBatch` used try/catch for both pausing and unpausing — a malicious relayer could dodge the pause by reverting.
**After:** When `paused == true`, failures now revert with `RelayerPauseFailed(relayer)`. When `paused == false`, the lenient try/catch + emit pattern is preserved so stuck relayers don't block recovery.

### 10. alpha-H001 — `commitWithAuthorization` trust assumption undocumented

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** Informational
**After:** Added NatSpec documenting relayer ordering trust assumption and ticketId binding.

### 11. beta-de16 — `_safeTransferExact` strict accounting undocumented

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** Informational
**After:** Added NatSpec documenting intentional over-checking for defense-in-depth with known ERC20 collateral.

### 12. alpha-H002 — No `revokeCommitAuthorization`

**File:** `contracts/zen/src/RelayerEscrow.sol`
**Severity:** Medium
**Before:** Users could `approveCommitAuthorization` but had no way to revoke before the relayer consumed it.
**After:** Added `revokeCommitAuthorization(address market, CommitAuth calldata auth)` with `UserMismatch` guard. New event `CommitAuthorizationRevoked`. Updated `IRelayerEscrow` interface.

### 13. hyp-factory-015 — ProtocolPool missing factory-lock guard

**File:** `contracts/zen/src/ProtocolPool.sol`
**Severity:** Medium
**Before:** `setMarketFactory` could be called repeatedly, allowing factory re-pointing after markets were registered.
**After:** Added `FactoryLocked` error and guard: `if (marketFactory != address(0) && marketFactory != factory) revert FactoryLocked()`. Matches the existing pattern in `RelayerEscrow`.

### 14. hyp-commit-024 — Commitment not validated against SNARK scalar field

**File:** `contracts/zen/src/RevealMarket.sol`
**Severity:** Medium
**Before:** `commitWithAuthorization` stored the `auth.commitment` hash without checking it was a valid BN254 field element. A commitment >= the SNARK scalar field modulus can never be proven in the ZK circuit, permanently locking the user's funds.
**After:** Added `if (uint256(auth.commitment) >= SNARK_SCALAR_FIELD) revert FieldElementOutOfRange()` in `commitWithAuthorization`, matching the validation already present in `_computeLeaf`.

### 15. hyp-pool-005 — `lpWithdraw` missing slippage protection

**File:** `contracts/zen/src/ProtocolPool.sol`
**Severity:** Medium
**Before:** `lpWithdraw(uint256 sharesToRedeem)` had no minimum output guarantee. Between TX submission and execution, a market `draw()` could reduce the share-to-asset ratio, giving the LP fewer assets than expected.
**After:** Added `minAssets` parameter: `lpWithdraw(uint256 sharesToRedeem, uint256 minAssets)`. Reverts with `SlippageExceeded()` if `convertToAssets(sharesToRedeem) < minAssets`. Pass `0` to skip the check.

## Findings Skipped (User-Confirmed OK)

| ID | Reason |
|----|--------|
| hyp-pool-001 | Accepted design: LP shares are 1:1, surplus accrues to protocol |
| hyp-pool-025 | Accepted design: owner withdraw is intentional for protocol operations |
| hyp-pool-004 | Accepted design: capacity model is correct for current risk budget |
| hyp-pool-021 | Accepted design: draw pause bypass for reserved markets is intentional |
| hyp-factory-001 | Accepted design: factory pause model is correct |

## Test Coverage

### Updated tests (breaking changes):
- `testRefreshLockedVerifierKeyHashCannotRewriteLockedAnchor` → rewritten as `testRefreshLockedVerifierKeyAllowsKeyRotation`
- `testSetRelayerCommitsPausedContinuesIfActiveRelayerFails` → rewritten as `testSetRelayerCommitsPausedRevertsIfActiveRelayerFails`
- `testSetMarketFactoryOnlyOwner` → updated to expect `FactoryLocked` revert
- `testFifoOrdering` → updated for automatic deposit compaction behavior

### New tests added:
- `testClearVerifierPinAllowsReApproval` — revoke + clearPin + re-approve after key rotation
- `testClearVerifierPinRevertsIfApproved` — cannot clear while approved
- `testExtendCommitDeadlineRevertsAfterWindowClosed` — warp past deadline, expect `CommitWindowClosed`
- `testClaimPauseTotalDurationCapped` — pause/unpause beyond 365 days, verify cap
- `testOracleClaimBoundedByTotalLiability` — excess payout reverts with `OverClaimed`
- `testSetOracleRevertsInCancelledPhase` — oracle rotation blocked in Cancelled
- `testCompactDepositsRemovesZeroRecords` — deposit/withdraw cycle, verify compaction
- `testSetMarketFactoryLockPreventsReassignment` — fresh pool factory lock
- `testRevokeCommitAuthorization` — approve then revoke, verify mapping cleared
- `testRevokeCommitAuthorizationRejectsWrongUser` — wrong user revoke blocked
- `testCommitRejectsOutOfFieldCommitment` — commitment >= SNARK scalar field rejected
- `testLpWithdrawSlippageGuard` — withdrawal reverts when assets < minAssets
- `testLpWithdrawSlippageZeroBypass` — minAssets=0 skips slippage check

### Verification:
```
contracts/zen:     226 tests passed, 0 failed
contracts/polygon:  64 tests passed, 0 failed
```

## Remaining Considerations

- **Off-chain relayer ordering** (alpha-H001): The relayer can front-run or reorder commits within a block. This is documented as a trust assumption; mitigation is off-chain (rate limiting, monitoring).
- **Oracle key management** (gamma-flow4-001): The per-ticket ceiling bounds damage from a compromised oracle key but doesn't eliminate it. Oracle key rotation and monitoring remain critical.
- **Deposit compaction gas**: `_compactDeposits` is O(n) in deposit count. For LPs with very large deposit histories, explicit `compactDepositsFor` can be called by anyone to spread gas cost.
