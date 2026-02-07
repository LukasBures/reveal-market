# Contracts Zen TODO

**MVP - Critical**
- Validate `BATCH_SIZE=256` and `MERKLE_DEPTH=8` are consistent with prover.
- Confirm `Verifier` uses the correct circuit hash.

**MVP - High**
- Add tests for `lockBatches` and `verifyAndSettleBatched` flows.

**MVP - Medium**
- Add tests for `CommitAuth` nonce and expiry.

**MVP - Low**
- Add gas snapshot updates for recent changes.

**MVP - Nice to have**
- Add fuzz tests for batch settlement edge cases.

**Production - Critical**
- Confirm admin permissions and ownership transfers.

**Production - High**
- Add contract-level circuit hash upgrade procedure.

**Production - Medium**
- Add incident halt strategy for settlement failures.

**Production - Low**
- Add on-chain analytics for commitment counts.

**Production - Nice to have**
- Add defense-in-depth for escrow drains.
