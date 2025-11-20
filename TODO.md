# Reveal Market MVP Tracker

This doc lists the minimum cross-team work that must land before we can call the stack “MVP ready.” Anything not referenced here can slip to the next milestone.

## Snapshot priorities (Nov 2025)
- **Backend** – Provenance + settlement data must be stored locally so `/markets` always returns auditable narratives and payout history.
- **Contracts** – Groth16 proofs need production keys, rotation tooling, and replay persistence so on-chain receipts are defensible.
- **Frontend** – Investors must see real data everywhere (charts, search, proofs) and be able to export diligence artifacts without leaving the site.
- **Proover** – Operators need artifact validation and Prometheus-grade telemetry so zk receipts remain trustworthy in production.

See the service-specific TODO files for deeper acceptance criteria.

### Backend MVP gaps
1. **AI summary ledger** – Persist every AI summary (model, prompt hash, context pointers, timestamps) and expose the history via `/markets/{event}` so diligence teams can audit narrative changes.
2. **Persistent resolution ledger** – Store resolution payloads (block #, tx hash, payout vector, oracle source) inside Postgres + Redis, and return them from `/markets` + `/proofs` without re-querying external APIs.
3. **On-chain mirroring & automation** – Stream MarketFactory events (create/rake/guardian updates) into Postgres and, when configured, queue settlement transactions once on-chain payouts finalize so the backend never drifts from contracts.

### Contracts MVP gaps
1. **Production Groth16 rollout** – Finalize audited proving/verifying keys, emit hashes on-chain, and ship rotation scripts/runbooks so every proof can be traced back to a known circuit version.
2. **Proof replay persistence** – Emit/store `proofNonce` + settlement receipts (backend + events) so auditors can prove no proof was replayed or tampered with.
3. **Guardian/ownership operations** – Document and test the `Ownable2Step` + guardian transfer process (including manifest ingestion) so we can rotate keys safely before onboarding partner capital.

### Frontend MVP gaps
1. **Live market telemetry** – Replace the placeholder `MarketDetailChart` with real price/liquidity history sourced from the backend/worker so detail pages show actual performance.
2. **Full search experience** – Ship a `/markets/search` surface (pagination, keyboard shortcuts, category pills) that calls the backend search endpoint instead of filtering placeholder cards.
3. **Proof & diligence surfacing** – Add filters (status, verifier, market) + CSV export on `/proofs`, and include a visible trust CTA so investors can self-serve receipts.

### Proover MVP gaps
1. **Artifact validation command** – Provide a CLI/env check that verifies `settlement_final.zkey` and `settlement_js` before the prover boots outside Docker so operators don’t accidentally run with stale artifacts.
2. **Prometheus metrics** – Expose latency/concurrency counters via `/metrics` (histograms + gauges) so ops can alert on proof slowdowns and stalled queues.

Keep scope tight—shipping these items unblocks the MVP announcement.

• Here’s how the pieces line up when you mirror Polymarket (or any oracle) but add Reveal’s “private while live, provable at the end” flow:

  1. During the market (“commit” phase)
      - Your UI shows curated metadata (titles, odds windows, sponsor info), but no live orderflow.
      - Users buy tickets by submitting sealed commitments (hash of their outcome, stake, salt). You escrow their ZEN in your contract. Nothing leaks on-chain besides “someone committed X ZEN to market Y.”
      - In parallel, you hedge by taking the equivalent exposure on Polymarket (or another venue). You can batch these hedges to match your internal book—think of it as a delta-neutral set of positions on Polymarket so you’re never directionally exposed.
  2. Market closes & oracle publishes outcome
      - Once Polymarket resolves (or your oracle posts the winning outcome), you settle that external hedge and read the final payout vector: for each outcome, what fraction of the pooled stake wins, and what rake Polymarket took. That gives you the ground truth numbers you need to square your internal pool.
      - You also have your internal ledger of commitments (who staked what, salt, outcome). Those commitments stayed private until now.
  3. Proof generation
      - This is where the Groth16 circuit fits. You feed two things into the circuit:
        • the internal commit set (hashes + salts + stakes + outcomes),
        • the final outcome vector (and any optional rake overrides you applied).
      - The circuit checks:
        • only commits made before the lock time are included (no late tickets),
        • the sum of winning stakes equals the revealed pool minus rake,
        • each ticket’s payout matches the pool math,
        • rake percentage is within configured bounds.
      - The circuit outputs a succinct proof plus public signals (market ID, outcome, total pool, rake, aggregate winners). The prover service (our “proover”) does this offline once per resolution.
  4. Publish + pay
      - You post the proof on-chain (or to your backend) along with the payout vector. On-chain verifier confirms it.
      - Once verified, your contract lets each user reveal their salt, prove they had a winning commitment, and claim the precomputed payout. Losing tickets never need to reveal, so they stay private forever.
      - Because you hedged on Polymarket, you cover all winning payouts from the external settlement—you’re effectively a private frontend + liquidity router that guarantees fairness with the proof.

  In short: you curate markets and hide live odds during the round, hedge externally so you don’t take risk, then use the ZK circuit to prove your internal pool math matches the published outcome. The user sees “private while live, provable at the end,” and Horizen gets a fully private-but-verifiable
  settlement system.
