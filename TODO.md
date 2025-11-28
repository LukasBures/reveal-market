# Reveal Market MVP Tracker

This doc lists the minimum cross-team work that must land before we can call the stack “MVP ready.” Anything not referenced here can slip to the next milestone.

## Snapshot priorities (Nov 2025)
- **Backend** – Provenance + settlement data must be stored locally so `/markets` always returns auditable narratives and payout history. (Commitment/settlement schema added; Merkle/payload builder wired; ingestion/backfill still needed.)
- **Contracts** – Groth16 proofs need production keys, rotation tooling, and replay persistence so on-chain receipts are defensible.
- **Frontend** – Investors must see real data everywhere (charts, search, proofs) and be able to export diligence artifacts without leaving the site.
- **Proover** – Operators need artifact validation and Prometheus-grade telemetry so zk receipts remain trustworthy in production.
- **Limits & gating** – Enforce per-bet and per-user caps off-chain (UI + API/hedger) and document on-chain equivalents for future hardening.
- **CORS/stream alignment** – Keep API and price-streamer CORS settings in sync with frontend origins so FX, history, and stream endpoints stay reachable in browser builds.

See the service-specific TODO files for deeper acceptance criteria.

### Backend MVP gaps
1. **Persistent resolution ledger** – Store resolution payloads (block #, tx hash, payout vector, oracle source) inside Postgres + Redis, and return them from `/markets` + `/proofs` without re-querying external APIs. (Commitments/settlements tables exist; Merkle/payload builder implemented; must ingest real on-chain commits/resolutions and backfill Merkle paths/pool totals/liabilities/rake/winning outcomes/circuit hash.)
2. **On-chain mirroring & automation** – Stream MarketFactory events (create/rake/guardian updates) into Postgres and, when configured, queue settlement transactions once on-chain payouts finalize so the backend never drifts from contracts. (Proof generation path now expects persisted settlement state; hook ingestion + prover triggering.)
3. **Bet caps enforcement** – Off-chain enforce per-bet cap (100 ZEN), per-user-per-market cap, and per-market ZEN cap; document on-chain cap requirements (maxTicketStake, maxUserStakePerMarket) for a future circuit/contract upgrade.

### Contracts MVP gaps
1. **Production Groth16 rollout** – Finalize audited proving/verifying keys, emit hashes on-chain, and ship rotation scripts/runbooks so every proof can be traced back to a known circuit version. (10-signal circuit regenerated; `contracts/cache/settlement-vk.json` updated with circuitHash; deploy scripts ready—need live deploy + artifacts/addresses.)
2. **Proof replay persistence** – Emit/store `proofNonce` + settlement receipts (backend + events) so auditors can prove no proof was replayed or tampered with. (Backend settlements table has proof status/hash/request id fields; ingestion path to persist hashes still pending.)
3. **Guardian/ownership operations** – Document and test the `Ownable2Step` + guardian transfer process (including manifest ingestion) so we can rotate keys safely before onboarding partner capital.
4. **Stake caps (future on-chain)** – Add maxTicketStake and maxUserStakePerMarket to RevealMarket/Factory so on-chain rejects oversize commits; mirror off-chain caps until then.

### Frontend MVP gaps
1. **Proof & diligence surfacing** – Add filters (status, verifier, market) + CSV export on `/proofs`, and include a visible trust CTA so investors can self-serve receipts.
2. **Bet limit UX** – Persistently surface per-bet and per-user caps in stake inputs and disable actions when limits are exceeded or FX/market data is stale.

### Proover MVP gaps
_Completed_: artifact validation CLI (`cmd/verify-artifacts`) wired into CI and startup; Prometheus metrics exposed at `/metrics`.

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
  9. circuitHash          (bytes32 mapped into field)
  10. padding             (uint256, fixed to 0 to enforce array length)

  For MVP, we assume K = 2 outcomes (YES/NO) and keep the padding slot to pin the verifier to 10 signals.

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



____
 Regenerate the circuit/vk/zkey to the finalized 10-signal layout (no commitmentsCount), compute circuitHash from key hashes, and update verifier JSON + contract bindings/
     tests accordingly.

• Here’s the concrete sequence to move everything to the finalized 10-signal, no-commitmentsCount layout and bind circuitHash to the key hashes:

  1. Update the circuit to the new signals

  - Edit prover/circuits/settlement.circom so the public signals (in order) are: merkleRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, poolTotalYes,
    poolTotalNo, circuitHash (and a final padding slot if you want to keep array length 10). Remove the commitmentsCount input/output and its non-zero constraint. Keep winner/
    rake/pool/liability guards.
  - Regenerate the build artifacts with your existing script: from prover/, run npm install (if needed) then ./circuits/generate_keys.sh (or your chosen snarkjs pipeline) to
    produce fresh settlement_final.zkey, settlement.wasm, settlement_js, and public.json.

  2. Compute the hashes and circuitHash

  - Proving key hash: keccak256 of the raw settlement_final.zkey bytes.
  - Verification key hash: keccak256 of the raw verifier JSON (after you export it).
  - circuitHash = keccak256(abi.encodePacked("reveal_settlement_v1", "1.0.0", PROVING_KEY_HASH, VERIFICATION_KEY_HASH)).
  - You can script it, e.g.:

    python - <<'PY'
    import hashlib, json, eth_hash.auto as keccak, pathlib
    pk = pathlib.Path("prover/circuits/build/settlement_final.zkey").read_bytes()
    vk_json = pathlib.Path("prover/circuits/build/verification_key.json").read_bytes()
    pk_hash = keccak.keccak_256(pk).hexdigest()
    vk_hash = keccak.keccak_256(vk_json).hexdigest()
    preimage = b"reveal_settlement_v1" + b"1.0.0" + bytes.fromhex(pk_hash) + bytes.fromhex(vk_hash)
    circuit_hash = keccak.keccak_256(preimage).hexdigest()
    print("proving_key_hash=0x"+pk_hash)
    print("verification_key_hash=0x"+vk_hash)
    print("circuit_hash=0x"+circuit_hash)
    PY
    (Adjust paths if your build directory differs.)

  3. Export the new verifier JSON

  - Use snarkjs (or noir) to export the verifier points for the new 10-signal layout:

    snarkjs zkey export verificationkey prover/circuits/build/settlement_final.zkey prover/circuits/build/verification_key.json
    snarkjs zkey export solidityverifier prover/circuits/build/settlement_final.zkey > /tmp/Verifier.sol
  - Copy the IC/alpha/beta/gamma/delta values into contracts/zen/cache/settlement-vk.json with expectedInputs: 10 and circuitHash set to the computed value above. (Keep the
    schema: alpha1, beta2, gamma2, delta2, ic, circuitHash, expectedInputs.)

  4. Update Solidity bindings

  - contracts/zen/src/RevealMarket.sol: drop commitmentsCount from SettlementSignals, _decodeSignals, and proof checks. Remap indices to the new order and keep uint256[10] so the
    verifier still enforces length 10. Remove the InvalidProofLayout checks that referenced commitmentsCount from public signals; keep the local commitmentsCount storage checks.
  - contracts/zen/src/interfaces/IVerifier.sol: keep verifyProof(bytes,uint256[10]) but document the new ordering.
  - contracts/zen/src/Verifier.sol: set EXPECTED_INPUTS to 10 (it already takes it from the vk JSON), and update any tests expecting the old 6-input config.
  - Update contract tests that asserted on the old signal ordering or commitmentsCount.

  5. Update the prover backend

  - prover/groth16_prover.go: adjust buildWitnessInput/validateRequest to emit only the new 9 (or 10 with padding) public inputs in the spec order; drop commitmentsCount. Ensure
    readPublicSignals expects length 10.
  - prover/circuits/settlement.circom public outputs must match the contract indexing; regenerate public.json and keep the order consistent.
  - prover/main.go/settlementProofRequest: keep the same request schema, but when building the witness/publicSignals, map to the new ordering and ensure the returned
    public_signals array length is 10.
  - Update prover tests that assert on publicSignals length/order.

  6. Wire the new verifier key into deployments

  - Replace contracts/zen/cache/settlement-vk.json with the regenerated values.
  - Re-run forge test in contracts/zen to ensure the new layout is accepted.
  - Use the new vk JSON when running contracts/zen/script/Deploy.s.sol (set SETTLEMENT_VK_PATH to your regenerated file) so the verifier on-chain has the correct IC length and
    circuitHash.

  7. Document the hashes

  - Record proving key hash, verification key hash, and the resulting circuitHash in contracts/zen/docs/settlement-circuit.md (and any ops docs) so the binding is auditable.

  That’s the full path: change circuit -> regenerate pk/vk/zkey -> compute hashes -> refresh vk JSON/circuitHash -> update Solidity/prover code to the new ordering -> rerun
  tests.



  2. Add Horizen testnet presets (RPC/WS/explorer, chain id 2651420, REVEAL_OWNER/GUARDIAN/TREASURY envs), wire wagmi/WalletConnect to that chain, and ship a
     DeployHorizenTestnet.s.sol that writes deployments/horizen-testnet.json.
  3. Build the minimal testnet UI (connect wallet on Horizen, commit form with salt/ticketHash, show locked merkleRoot, settlement/proof status + explorer link, basic “My
     tickets” view) and hook the backend to call prover then settleMarket on-chain.


____


Anonymous Prediction Market – Full Economic & Payment Logic Specification (MVP)
=========================================================================================

1. Overview
-----------
This document describes the complete economic, payout, hedging, and liquidity-provider (LP)
architecture for the anonymous prediction‑market MVP. It is written in clear paragraphs and
structured instructions so that an AI coding assistant (e.g., Codex) can directly implement the
system. The platform supports a dual‑asset flow: users place bets in ZEN, receive stake refunds
in ZEN minus rake, and receive winnings (profit) in USDC. The LP pool on Polygon is
USDC‑only and funds the hedger. Only the platform owner may borrow from the LP pool.
All parameters such as haircut, worsen spread, and rake must be fully configurable.

2. Platform Parameters (Configurable)
-------------------------------------
The platform must expose configuration values that can be adjusted without changing code.
These values must be stored in a configuration module or contract:

- haircut_percent (recommended default: 10–12.5%)
- worsen_percent (recommended default: 3%)
- rake_percent (recommended default: 1.5–2%)
- lp_share_percent (recommended default: 15–20%)

The platform must compute total_monetisation dynamically as:
total_monetisation = haircut_percent + worsen_percent + rake_percent

These parameters must be used consistently across betting logic, hedger logic, pricing
engine, settlement, LP revenue share calculations, and risk management.

3. Asset Flow Model
--------------------
The system uses two assets:

- ZEN for user-facing operations (bettor stakes and rake collection)
- USDC for hedging, payouts of profit, internal treasury, and LP pool operations

ZEN and USDC must be kept strictly separate in accounting, payout logic, and treasury
management. Users interact exclusively with ZEN for placing bets and receiving stake refunds.
Profit payouts must be executed in USDC. All hedging operations and LP payouts are USDC‑denominated.

4. User Bet Lifecycle
----------------------
When a user submits a bet, the system receives:

- user_id
- market_id
- outcome selection
- stake_zen

The pricing engine must:

1. Display worsened odds to the user using worsen_percent.
2. Apply rake_percent only on payout/refund, not on displayed odds.
3. Apply haircut_percent internally to calculate the hedging exposure in USDC.

Codex must convert the ZEN stake into a USDC hedging amount using:

hedge_usdc = (stake_zen * zen_price_usdc) * (1 - haircut_percent)

This USDC amount must be borrowed from the LP pool.

5. Hedging Logic
-----------------
The hedger is the only component allowed to borrow USDC from the LP pool. When a bet is
placed:

1. Convert the ZEN stake to USDC-equivalent exposure.
2. Apply haircut to determine reduced hedge volume.
3. Borrow this USDC amount from the LP pool.
4. Execute a hedge position on an external market such as Polymarket.

The hedger must track:

- hedge_position_id
- hedge_cost_usdc
- expected_usdc_payout_if_win
- expected_usdc_liability_if_loss

Upon resolution, the hedger must close or settle each hedge and return borrowed USDC plus
LP revenue share.

6. Settlement Logic
--------------------
When the market resolves:

If the user LOSES:
- stake_zen becomes platform ZEN revenue.
- hedger settles external position.
- any hedger PnL in USDC contributes to platform and LP revenues.

If the user WINS:
A) Refund stake in ZEN minus rake:
   refund_zen = stake_zen * (1 - rake_percent)
   rake_zen = stake_zen * rake_percent (platform revenue)

B) Pay profit in USDC:
   profit_usdc = expected_usdc_payout_if_win - hedge_cost_usdc
   payout_profit_usdc = max(0, profit_usdc)

C) Repay LP pool:
   lp_share_usdc = total_platform_usdc_revenue * lp_share_percent
   repay_amount_usdc = borrowed_usdc + lp_share_usdc

7. LP Pool (Polygon, USDC‑only)
-------------------------------
The LP pool holds only USDC. Liquidity providers may deposit or withdraw USDC at any time.
LPs receive a proportional revenue share, not a fixed APY. This prevents insolvency, avoids
ponzi dynamics, and ties payouts to real platform activity.

LPs receive:
lp_share_usdc = platform_total_usdc_revenue * lp_share_percent

LP yield (APY) is:
lp_apy = (lp_share_usdc * 12) / lp_total_pool_usdc

Small pool = high APY
Large pool = stabilized APY

This dynamic model is crucial for sustainability.

8. Pricing Engine
------------------
The pricing engine must:

- Apply haircut to internal hedge exposure.
- Apply worsen spread to displayed odds.
- Calculate potential payouts.
- Ensure no external market is ever given superior odds (bot protection).

Haircut makes hedging safer and gives the platform internal margin.
Worsen ensures user-facing odds are slightly disadvantageous, monetising privacy.
Rake ensures stable, predictable platform revenue.

9. Treasury Accounting
-----------------------
Treasury must maintain two independent ledgers:

1. ZEN ledger:
   - Receives rake_zen
   - Receives losing-stake ZEN
   - Never used for hedging

2. USDC ledger:
   - Receives hedger profits
   - Receives haircut + worsen monetisation
   - Pays LP share
   - Pays user USDC winnings
   - Stores long-term treasury

These two ledgers must never be mixed.

10. User-Facing Rules (must be shown in UI)
--------------------------------------------
The platform must clearly display:

“You bet in ZEN. If you win, you receive:
 • Your stake back in ZEN minus the platform rake.
 • Your winnings in stable USDC, so your profit is protected from volatility.”

This must be visible in the confirmation modal and payout summaries.

11. Failure Handling
---------------------
Codex must implement fail-safes:

- If LP pool lacks USDC, disable new bets.
- If hedge execution fails, reject new bets and pause market.
- If payout_usdc < 0 due to slippage, set payout_usdc = 0.
- If oracle for ZEN/USDC price fails, disable betting temporarily.
- All configurable parameters must have safety limits (e.g., haircut < 25%).

12. Modules Codex Must Implement
---------------------------------
The system must consist of:

- pricing_engine.py
- bet_processor_zen.py
- hedger_usdc.py
- settlement.py
- treasury_manager.py
- LPUSDCVault.sol (smart contract)
- config.py (for configurable parameters)

Each module must be deterministic, side-effect aware, and isolated in responsibilities.

13. Summary
------------
This architecture provides:
- A ZEN-facing anonymous betting system.
- USDC‑based hedging and profits.
- Configurable monetisation parameters.
- Safe LP mechanics with variable yield.
- Clean economic separation between ZEN (user side) and USDC (backend side).


____



  Hard

  - Contracts: Merkle accumulator replacement and circuit/public-signal alignment; add on-chain stake caps (maxTicketStake/maxUserStakePerMarket); fuzz/tests for commitWithQuote digest/replay/expiry and signer upgrades.
  - Backend/worker: persistent resolution ledger + on-chain mirroring (Factory events) and optional settlement automation; ingest real commitments/settlements to back proofs; durable quote audit store.
  - Frontend+TX path: fully wire commitWithQuote UX (refresh on expiry, chain mismatch handling) and error surfacing; ensure single FX WS reuse across pages.
  - Hedger: real Polymarket/vault/bridge clients with slippage/unwind logic, replay-safe offsets/locks, and settlement integration with prover payloads.

  Hard

  - Contracts/circuits: real Merkle accumulator + circuit/public-signal alignment; add on-chain stake caps and fuzz/tests for commitWithQuote (replay/expiry/digest).
  - Backend/worker: ingest on-chain commitments/settlements, persistent resolution ledger, and optional settlement automation; durable replay/audit store for quotes.
  - Frontend/tx flow: full commitWithQuote UX (expiry refresh, chain mismatch handling), and richer bet-cap UX tied to API caps.
  - Hedger: production-grade Polymarket/vault/bridge integrations with slippage/unwind, replay-safe offsets/locks, and settlement/prover payload handoff.


• Remaining gaps in contracts/zen (highest to lowest):

  - Proof/Merkle binding (still high risk): Circuit doesn’t prove commitments inclusion or aggregate winning stakes. Prover/oracle can still fabricate pools/roots; claims rely on off-chain honesty. Needs circuit upgrade + contract alignment (Merkle accumulator, sum of winning stakes, binding to tickets).
  - Merkle accumulator robustness: Current tree is basic keccak array; no frontier/MMR, no ordering guarantees beyond insertion. Large commitment counts could make lock() expensive; consider canonical accumulator, min stake, and/or max commitments per market.
  - Governance surface: Guardian still has broad powers (pauses, cancel, emergency settle). Float withdrawals are now restricted to treasury/factory/owner, but consider timelocks/multisig for controller actions and clearer separation of duties.
  - Risk caps configurability: On-chain per-market caps exist; optional minCommitmentSize/maxTicketsPerUser are set at deploy time. There’s no dynamic update path—decide if you need ability to tighten caps post-deploy or keep immutable.
  - Circuit/verification assumptions: Verifier remains 10-signal; any circuit change requires new deployment. No zk attestations beyond on-chain verify/stub—document operational steps for vk rotation and ensure frontend/backend surface the circuit hash.
  - Operational invariants not enforced on-chain: No per-claimer payout caps, no maxUserStakePerMarket on-chain, no aggregate accounting invariant beyond coverage checks. Consider adding if risk appetite requires.
  - Docs/runbooks: README/TODO mention future work (Merkle upgrade, circuit hash binding). Update deployment/runbooks when circuit upgrades land to avoid drift.


  - Keep factory ownership with a secure multisig/timelock so no one else can deploy rogue markets.
  - You can leave createMarket unused; it won’t do anything unless the owner calls it with a payable float amount (if any).
  - If you want to prevent any future market creation entirely, you can optionally transfer ownership to a burn address or timelock with no proposer, but that also blocks updates to guardian/risk limits.

› 

  