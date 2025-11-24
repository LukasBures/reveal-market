# ZEN Contracts TODO / Hardening Backlog

## Proof / Commitments
- Replace the rolling `commitmentsRoot = keccak256(prevRoot, ticketHash)` with a canonical Merkle accumulator (Keccak leaves, fixed ordering, MMR/frontier) so Merkle proofs are meaningful and circuit-compatible. Update public signals + circuits accordingly.
- If sticking with Merkle: add tests for inclusion/exclusion, proof ordering, and failure cases; reject zero-length proofs unless single-leaf root matches.
- Bind settlement to a stored `circuitHash` public signal to prevent replay across verifier upgrades; consider storing `expectedInputs` too.

## Risk / Accounting
- Add invariant/fuzz tests ensuring `escrow + float + paidOut >= totalLiability` across all flows (commit/settle/claim/refund). Current invariants cover a subset.
- Consider per-claimer payout caps to avoid extreme multipliers if MAX_PAYOUT_MULTIPLIER is raised in future.
- Add configurable on-chain stake caps (maxTicketStake, maxUserStakePerMarket) to mirror off-chain bet limits; wire into Factory/RevealMarket and tests.

## Deployment / Ops
- Update deployment docs/runbooks to match native-only collateral, 12 public signals, and max payout multiplier rules.
- Add a sanity lint/CI step for forge-lint in the contracts job.
- Add a note in deployment runbooks about frontend/API/streamer CORS origins to avoid blocked explorer links in staging.

## Observability
- Add events for factory risk sync failures (currently silent) if you want explicit alerts on accounting drift.

## Merkle/Circuit Alignment
- Decide on final Merkle leaf encoding (ticketHash vs keccak(ticketHash)) and keep circuit/public-signals consistent; document this in README + docs/settlement-circuit.md.

## Tests
- Add property/invariant tests for pause/guardian controls across multiple actors; fuzz commit/settle/claim sequences with random pause toggles.
- Add fuzz for proof replay attempts with mismatched circuitHash/version/market address once circuitHash is surfaced.
