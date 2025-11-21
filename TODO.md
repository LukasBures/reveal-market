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
      - The circuit outputs a succinct proof plus public signals (market ID, outcome, total pool, rake, aggregate winners). The prover service (our “prover”) does this offline once per resolution.
  4. Publish + pay
      - You post the proof on-chain (or to your backend) along with the payout vector. On-chain verifier confirms it.
      - Once verified, your contract lets each user reveal their salt, prove they had a winning commitment, and claim the precomputed payout. Losing tickets never need to reveal, so they stay private forever.
      - Because you hedged on Polymarket, you cover all winning payouts from the external settlement—you’re effectively a private frontend + liquidity router that guarantees fairness with the proof.

  In short: you curate markets and hide live odds during the round, hedge externally so you don’t take risk, then use the ZK circuit to prove your internal pool math matches the published outcome. The user sees “private while live, provable at the end,” and Horizen gets a fully private-but-verifiable
  settlement system.



Reveal Market — Horizen Testnet Implementation Inputs (Finalized Spec)
=========================================================================

This document answers all the implementation questions so work can proceed without guesswork.

1) Horizen Testnet Details
--------------------------

- Network name: Horizen Testnet (Caldera / zkVerify)
- Chain ID: 2651420

- RPC URLs:
  - HTTP: https://horizen-testnet.rpc.caldera.xyz/http
  - WebSocket: wss://horizen-testnet.rpc.caldera.xyz/ws

- Block explorer base URL:
  https://horizen-testnet.explorer.caldera.xyz
  - Example address:
    https://horizen-testnet.explorer.caldera.xyz/address/<ADDRESS>
  - Example tx:
    https://horizen-testnet.explorer.caldera.xyz/tx/<TX_HASH>

- Native token:
  - Symbol: ETH
  - Decimals: 18

These should be parameterized in env files so we can easily switch to mainnet later.

2) Admin / Ops Parameters
-------------------------

We define the roles and economic parameters up-front so contracts, scripts, and docs are aligned.

- Owner address (protocol owner / admin multisig for now):
  - OWNER = your main deployer / ops wallet (replace with safe later).
  - For implementation, treat OWNER as an env var: REVEAL_OWNER_ADDRESS.

- Guardian address (emergency pause / circuit upgrade safety):
  - GUARDIAN = a separate hot wallet (or second signer) from OWNER.
  - Env var: REVEAL_GUARDIAN_ADDRESS.

- Treasury address (where rake accumulates):
  - TREASURY = StormBoost / Reveal multisig for now.
  - Env var: REVEAL_TREASURY_ADDRESS.

- Rake basis points (bps):
  - MAX_RAKE_BPS (constant): 200 (2% hard cap).
  - Target rake for MVP markets: 100 bps (1% on the winning pool).
  - Contract invariant: require(rakeBps <= MAX_RAKE_BPS).

- Market size caps (per market; can be refined later):
  - MAX_TOTAL_ESCROW_PER_MARKET: 100_000 * 1e18 (100k ZEN equivalent).
  - MAX_TICKET_AMOUNT: 5_000 * 1e18 (5k ZEN equivalent).
  - These should be constants in the contracts and also documented.

- Payout multiplier cap:
  - For any fixed-odds style multiplier: MAX_MULTIPLIER = 20x (scaled by 1e18 if using fixed-point).
  - If using pure pari-mutuel, multiplier is emergent, but we still enforce numerical safety (no overflow)
    in the circuit and contracts.

- Float / escrow funding expectations:
  - Escrow:
    - All user deposits for tickets are held as escrow in the market contract.
  - Float:
    - Protocol “float” (rake and treasury-only balances) is accumulated in TREASURY.
    - We do NOT rely on external float for solvency in v1; every market is self-contained:
      escrow + float + paidOut >= totalLiability must hold within the contract/accounting model.
  - There is NO leverage / undercollateralized behavior in v1.

3) Merkle / Circuit Specifics
-----------------------------

- Final leaf encoding:
  - ticketHash = keccak256(abi.encodePacked(marketId, user, outcomeId, amount, salt))
  - leaf = keccak256(abi.encodePacked(ticketHash))
  - This is the canonical leaf for all circuits and Merkle trees.

- Merkle tree hash:
  - Internal node hash: keccak256(abi.encodePacked(left, right)).
  - Binary Merkle tree, complete tree representation off-chain, root only stored on-chain.

- Proof depth:
  - We treat depth as unbounded at the protocol level (depends on number of leaves),
    but in practice circuits will be compiled with a max depth (e.g. 32).
  - We choose a MAX_TREE_DEPTH = 32 for the initial circuits, which comfortably supports up to 2^32 tickets
    (way beyond any realistic MVP usage).
  - The circuit will have a fixed depth, padding empty leaves as needed.

- Non-empty proof rule:
  - For markets with a single ticket, the Merkle root equals the leaf and Merkle paths have length 0.
  - For all other cases (more than one leaf), we enforce that Merkle paths are non-empty.
  - In practice:
    - Circuit logic:
      - If commitCount == 1, allow zero-depth path (root == leaf).
      - Otherwise, require full path of MAX_TREE_DEPTH levels (with padding at empty branches).

4) Verifier / Circuit Binding
-----------------------------

We want a deterministic, auditable definition of circuitHash and public signals.

- circuitHash derivation:
  - circuitHash = keccak256(abi.encodePacked(
        CIRCUIT_NAME,
        CIRCUIT_VERSION,
        PROVING_KEY_HASH,
        VERIFICATION_KEY_HASH
    ))
  - CIRCUIT_NAME: "reveal_settlement_v1"
  - CIRCUIT_VERSION: semantic version string, e.g. "1.0.0"
  - PROVING_KEY_HASH: keccak256 hash of the proving key file bytes.
  - VERIFICATION_KEY_HASH: keccak256 hash of the verification key file bytes.

  Both hashes and the resulting circuitHash MUST be documented in the repo and in the technical doc.

- Public signals order (finalized):

  We fix an explicit order:

  1. merkleRoot           (bytes32 mapped into field)
  2. marketId             (uint256)
  3. winningOutcomeId     (uint256)
  4. totalEscrow          (uint256)
  5. totalLiability       (uint256)
  6. rakeBps              (uint256)
  7. poolTotal_0          (uint256)
  8. poolTotal_1          (uint256)
  9. ... poolTotal_(K-1)  (uint256, K outcomes, K fixed per circuit)
  10. circuitHash         (bytes32 mapped into field)

  For MVP, we assume K = 2 outcomes (YES/NO).
  That gives 10 public signals total.

- Max public inputs / signals:
  - We will compile circuits with a fixed K and field size, but in the Solidity verifier we enforce:
    - require(publicInputs.length == 10) for K = 2.
  - This prevents arbitrary extra public inputs from sneaking in.

5) Prover API & Keys
--------------------

- Endpoint path:
  - Base URL: PROVER_URL (env var).
  - Proof generation endpoint: POST /prove
  - Health check: GET /healthz

- Request schema (JSON):

  {
    "marketId": "<uint256>",
    "merkleRoot": "<0x-prefixed hex>",
    "winningOutcomeId": "<uint256>",
    "tickets": [
      {
        "user": "<0xaddress>",
        "outcomeId": "<uint256>",
        "amount": "<string-decimal-or-hex-uint256>",
        "salt": "<0xbytes32>",
        "ticketHash": "<0xbytes32>",
        "leaf": "<0xbytes32>",
        "merklePath": ["<0xbytes32>", ...],
        "merkleIndex": "<uint256>"
      },
      ...
    ],
    "poolTotals": ["<uint256>", "<uint256>"],   // YES/NO totals
    "totalEscrow": "<uint256>",
    "totalLiability": "<uint256>",
    "rakeBps": "<uint256>",
    "circuitHash": "<0xbytes32>"
  }

- Response schema (JSON):

  {
    "proof": {
      "pi_a": ["<hex>", "<hex>"],
      "pi_b": [["<hex>", "<hex>"], ["<hex>", "<hex>"]],
      "pi_c": ["<hex>", "<hex>"]
    },
    "publicSignals": [
      "<uint256-as-decimal-string>",
      ...
    ]
  }

  This matches the common snarkjs Groth16 layout.

- Proving key location:
  - On disk inside the container at /keys/reveal_settlement_v1_final.zkey.
  - Verification key at /keys/reveal_settlement_v1_vk.json.
  - Their hashes are used in circuitHash derivation (see above).

- Timeouts:
  - No on-chain timeouts (EVM cannot enforce a wall-clock timeout).
  - Off-chain:
    - Default proof timeout: 60 seconds for MVP (configurable).
    - If the prover fails or times out, the backend will not call settleMarket and instead log an error and expose status to the UI.

6) Deployment Strategy (Horizen Testnet)
----------------------------------------

- Contracts to deploy:
  - RevealMarketFactory (or MarketFactory equivalent).
  - Market implementation / template.
  - RakeManager / Treasury config contract (if separate).
  - Groth16 Verifier contract (SettlementVerifier).
  - Any role manager / Guardian contract if not embedded in the markets.

- Redeploy vs reuse:
  - For the testnet milestone we will perform a fresh, clean deployment:
    - Use new addresses for all core contracts.
    - Tag them as "horizen-testnet-v1".
  - This avoids any ambiguity from previous experiments.

- Deploy script:
  - Use Foundry scripts:
    - script/DeployHorizenTestnet.s.sol
  - Script responsibilities:
    - Read env vars for OWNER, GUARDIAN, TREASURY, RPC URL.
    - Deploy Verifier.
    - Deploy MarketFactory with references to Verifier, TREASURY, initial rakeBps, and MAX caps.
    - Output addresses in:
      - deployments/horizen-testnet.json

7) Frontend Scope (Minimal Testnet UI)
--------------------------------------

We keep the frontend minimal but complete for the milestone.

Views:

1. Home / dashboard:
   - List one or a few test markets (hard-coded or fetched from backend).
   - Each entry links to a market detail page.

2. Market detail page:
   - Connect wallet (Horizen testnet).
   - Show market metadata (question, outcomes).
   - Commit form:
     - Choose outcome.
     - Enter amount.
     - Frontend generates salt (random bytes32).
     - Computes ticketHash and calls commit() on the contract.
   - Show current status:
     - COMMIT / LOCKED / SETTLED (fetched from contract).
   - Display merkleRoot once frozen:
     - Show "Commitment root: 0x..." read from contract.
   - Proof / settlement status:
     - When settlement occurs, show:
       - winning outcome,
       - "Proof verified" flag (read from contract or event),
       - link to the settlement transaction in the Horizen explorer.

3. Optional: Simple "My tickets" view
   - List user’s commits by querying events filtered by user address.

Placement:

- We use a dedicated route /markets/[id] for the main demo, linked from the home page.

8) Demo Expectations
--------------------

- Markets to demo:
  - One canonical YES/NO market, e.g.:
    - "Will the ZEN/USD price close above X on date Y?"
  - Alternatively, a simple internal/demo question that does not depend on external APIs:
    - "Testnet demo market #1" with pre-scripted outcome.

- Narrative:
  - Show:
    1) User connects wallet.
    2) User commits a ticket (no odds or positions revealed).
    3) Commit phase ends; commitments are frozen; merkleRoot displayed.
    4) Oracle resolves market; backend generates ZK proof.
    5) Admin calls settleMarket with proof.
    6) UI updates to show "Proof verified, market settled".
    7) User claims winnings if they selected the winning outcome.

- Data:
  - Prefer live interaction for authenticity:
    - Real commit TXs on Horizen testnet during recording.
    - Real settlement TX using prover-generated proof.
  - We can still script the resolution to avoid dependency on external price feeds.

9) Beta Evidence Plan
---------------------

We need a clear plan for “independently verifiable proof of Beta testing with privacy verification and user feedback”.

- Who will test:
  - Small closed group:
    - You, your team (devs + Kamila).
    - 3–10 trusted community users (Horizen / crypto-native friends).
  - All instructed to:
    - Connect to Horizen testnet.
    - Commit to the demo market.
    - Wait for settlement.
    - Attempt claim.

- What to log:
  - Internally:
    - User addresses (anonymized in public artifacts if needed).
    - Tx hashes of commits, freeze, settlement, and claims.
    - Prover logs: proof_requested, proof_generated, proof_failed (if any).
  - For the grant submission:
    - Screenshots of:
      - UI during commit and after settlement.
      - Explorer pages for settlement transaction.
    - Short written feedback snippets:
      - “Was the flow understandable?”
      - “Did you see any live odds / positions?” (they should say no).
      - “Did settlement feel trustworthy knowing there is a proof?”

We will compile these into a small Beta report attached to the technical documentation and linked in the submission.

10) Implementation Commitments (Next Steps)
-------------------------------------------

Given the above confirmed inputs, the concrete next development steps are:

1. Lock Merkle and circuitHash spec in contracts and tests.
2. Align circuits/public signals to the finalized spec and regenerate proving/verifying keys; compute circuitHash.
3. Implement and test the SettlementVerifier integration and binding checks in the market contracts.
4. Add and validate deployment scripts for Horizen EON testnet, writing addresses to deployments/horizen-testnet.json.
5. Wire the prover endpoint into the backend (proof requests on resolution, settlement TX submission).
6. Implement the minimal frontend views (commit form, root display, settlement result / proof status).
7. Update the technical documentation and demo script to match this spec, including:
   - Privacy architecture,
   - ZK implementation details,
   - How to reproduce locally and on testnet,
   - Beta test evidence and links to explorer, logs, and screenshots.

This specification is now complete enough to implement the testnet milestone without guesswork and to satisfy the Project grant requirements for “privacy architecture plus ZK implementation”, a functioning testnet app, technical documentation, demo video, and beta testing proof.
