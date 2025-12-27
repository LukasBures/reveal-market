# MVP Delivery Specification (Testnet zk-proof demo)

This file describes the exact implementation scope to ship the MVP on Horizen Testnet and to demo end-to-end zk-proof settlement. Treat each section as blocking; wire logs/metrics to the unified format (`timestamp | LEVEL | logger | file:line | event | request_id`).

## 1) Environment & readiness baseline
- Chain/env defaults: chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, streamer FX endpoint `http://streamer:8100/fx/zen-usd`, prover enabled only when artifacts present. Ensure `RM_PRICING_CHAIN_ID`, signer key/address, and env vars are loaded; add a health/smoke check that fails fast if missing.
- CORS/CSP/connect-src: align API + streamer + frontend origins; update defaults and dev warnings when blocked. Ensure pricing FX endpoint passes CORS smoke test.
- Migrations/backfill: apply Alembic head (`0001_initial_schema.py`) and backfill normalized tables (outcomes, tags, clob tokens, market_gamma_metadata, gamma_raw). Confirm health probes see schema.
- Gamma stats exposure: surface bestBid/bestAsk/spread/volume/openInterest from Gamma into API schemas (MarketSummary/MarketDetail) and worker serialization; ensure cache tags update.
- Current gaps to close:
  - Defaults: `RM_PRICING_CHAIN_ID`/RPC/signer are unset (`None`) and .env still points at Polygon; pin Horizen defaults and derive signer address for checks.
  - Health: pricing signer check only degrades on missing envs; add a hard fail for missing/mismatched chain id, signer key/address, and RPC alignment; assert `PRICING_SIGNER_ADDRESS` presence.
  - CORS/CSP: API CORS only warns on wildcard; CSP connect-src still `self` so origin drift goes undetected. Streamer logs mismatches but has no smoke for frontend origin; frontend lacks dev warnings. Add a CORS/CSP smoke that proves `/pricing/fx` is reachable from the configured origin.
  - Schema/backfill: health only does `SELECT 1`; it never asserts Alembic head or schema version key. Add revision check and make sure markets are backfilled into normalized tables (outcomes/tags/clob tokens/gamma metadata/gamma_raw) with cache tags invalidated.
  - Gamma metrics: worker doesn’t populate bestBid/bestAsk/spread/openInterest; API schemas and cache enrichment don’t expose them; frontend types/mappers ignore them. Map them through ingestion → models → API responses → cache tags and update frontend types/mapper consumers.

## 2) Backend pricing, quotes, caps
- Quote issuance: `/pricing/quote` must ABI-pack QUOTE_V1 (chainId, market, wallet, outcomeId, stake_wei, fx_scaled 1e8, expiry, quoteId), sign with pricing key, and persist quotes durably (status, expiry, consumed_at). Reject missing/mismatched fields; log request_id and quoteId.
- Signer health: tighten `_check_pricing_signer` so `/health` surfaces derived chain id + signer address, compares against both env and configured values, and returns `error` (even in non-prod) when chain id or key is missing/mismatched. Include derived signer address/chain in the health component detail so ops can see what key is live; fail fast when `PRICING_SIGNER_ADDRESS` disagrees with the derived key or when `RM_PRICING_CHAIN_ID` differs from env.
- Cap enforcement: drop the per-bet cap to 0.1 ZEN (`max_stake_zen`), make `market_id`/`user_id` required for quote issuance, and ensure errors return structured limits (max + remaining per-user/per-market) alongside the failure reason. Enforce per-user-per-market and per-market caps server-side even when clients omit IDs; include remaining caps in successful responses. Add tests that cover boundary cases (exactly at cap, just over cap, missing IDs, mixed consumed/issued quotes, stale quote expiry in cap sums).
- FX handling: always pull FX from the streamer endpoint and propagate `stale` + `received_at`/timestamp metadata into `/pricing/fx` and quote responses so the frontend can block stale trades. `/pricing/fx` should warn and 503 when using fallback or stale data instead of silently returning 200 with a fallback price. `pricing_quote`/`pricing_submit` should reject stale FX, surface the FX timestamp/age in responses, and use the streamer timestamp when checking drift.

## 3) Frontend trading flow (commitWithQuote)
- Wallet/chain guard: enforce Horizen Testnet (2651420) in wagmi config + runtime; block quote/trade UI on wrong/missing chain or wallet. Prompt network switch CTA and auto-refresh quotes when chain/account changes; never reuse quotes from the wrong chain. Display connected chain vs pricing signer/chain returned by the API in the trade panel.
- Quote UX: outcome/stake picker calls `/pricing/quote` with wallet+market+outcome, renders live expiry countdown, FX timestamp/age/source, and caps. Auto-refresh quotes on expiry, chain drift, FX stale→fresh transitions, or manual refresh. Normalize error reasons (stale FX, missing wallet, wrong chain, caps exhausted). Keep a single shared FX WS connection per session (canonical `/fx/zen-usd` path) and reuse it across pages.
- Cap/stake enforcement: apply the 0.1 ZEN per-bet cap plus API caps (max/remaining per-user and per-market) to stake inputs and CTA disabled state. If remaining cap is 0, block quotes/trades and show the cap reason. Do not floor caps to 0.1 when API returns 0; clamp stakes to the smallest non-null cap and message the adjustment.
- Tx submission: build the signed payload and call `RevealMarket.commitWithQuote`; surface wallet gas prompt, pending, and confirmed states (wait for receipt) with hash display. Handle specific failures (expired/consumed quote, wrong chain/signature) with tailored messaging and auto-refresh quote on revert. Keep allowance flow visible (pending/confirmed) and keep submission blocked on wrong network or stale FX.
- Stale/cap guards + FX alignment: disable submit when FX is stale, quote expired, or caps exceeded; show explicit reason. Standardize FX path (`/fx/zen-usd` with alias to `/fx/zen-usdc`) and expose `received_at/lastUpdate` in the FX state so UI can display freshness and enforce guards.

## 4) Positions + claim
- Backend: expose positions endpoint (wallet-scoped) with stakes, entry FX, current FX, PnL, potential winnings, volume, aggregated stats; include claimable status.
- Frontend: positions dashboard showing active/resolved positions, PnL, potential winnings, totals; single “Claim winnings” CTA per claimable set.
- Claim flow: frontend calls `RevealMarket` claim; backend/worker mirrors claim in DB and updates resolution ledger/positions on success; show tx status and refreshed balances.

## 5) Resolution ledger & automation
- Ledger persistence: on resolution ingest, store condition ID, payouts, winners, oracle/question IDs, block number/timestamp, tx hash, and payload snapshot in Postgres + Redis. Expose via `/markets`, `/markets/{event}`, `/proofs`.
- On-chain mirroring: stream MarketFactory events (MarketCreated, RakeConfigured, guardian changes) into DB/Redis to prevent drift.
- Automation (optional flag): when payouts finalized, queue settlement transactions or alert ops with duplicate suppression and retry logging. Respect env toggle.
- Health/metrics: emit counters for resolution gaps, automation retries, and ledger writes.

## 6) Proofs pipeline (zk demo critical path)
- Worker ingest: ensure commitments and settlements populate DB tables; resolution ledger ties to proofs.
- Prover artifacts: regenerate Groth16 artifacts for updated settlement circuit (liability cap removed, 10 public signals). Publish verifying key hash and update on-chain verifier/circuitHash (contracts/zen).
- Prover service: on startup, verify artifacts (existence + optional hash); expose `/healthz` and `/metrics` (add Prometheus histograms/gauges for latency, inflight, errors). Document allowed origins/ingress.
- Proof requests: worker issues settlement proof requests to prover when market resolved and commitments present; store request_id/hash/status/timestamps; cache proofs in Redis.
- API exposure: `/proofs` and market detail endpoints include proof metadata (status, request_id, hash, created_at, verifier). Include resolution ledger info.
- Frontend: proofs page supports filters (status/verifier/market), CSV export, diligence CTA; detail view shows proof metadata. Claim/positions flow displays proof availability where relevant.
- Demo script: provide step sequence to show commit → resolution ingest → proof generated → claim succeeds on testnet using regenerated artifacts.

## 7) Search experience
- Backend endpoint: build search API with pagination, category pills, and keyboard shortcut support; returns markets ordered by relevance.
- Frontend: replace client-only filter with backend results; add pagination controls, category chips, and keyboard shortcuts.

## 8) Market history/chart
- Data source: provide historical price/liquidity from backend/streamer history endpoint; ensure SSE/WS or polling delivers recent points.
- Frontend: wire MarketDetail chart to real data; handle loading/empty states; update live if stream present.

## 9) CSP/CORS/FX alignment
- Streamer CORS/hosts: confirm allowlist includes frontend origin/WSS; update defaults/docs.
- Pricing FX CORS: add smoke test for `/pricing/fx` origin handling; warn on stale/fallback FX.
- Dev warnings: surface banner in frontend when streamer/API origins blocked or FX stale.

## 10) Data backfill + validation
- Run Alembic head and backfill normalized tables; verify cache hydration and feature caches (featured markets, suggest) still prime.
- Validate Gamma-derived stats in API responses and caches; add tests to ensure fields exist and are typed.

## 11) Contracts/zen tasks
- Regenerate Groth16 artifacts for settlement circuit; update verifier and `circuitHash`; redeploy to testnet; document addresses.
- Testing: add fuzz for Merkle inclusion/replay protection, protocol cap edges (draw failures), multi-claim sequencing.
- Deploy scripts: build env-driven scripts for market creation and protocol cap adjustments; include signer rotation/ownership notes and optional timelock/pauser guidance.
- Monitoring hooks: add events/metrics for protocol pool draws and relayer credits if downstream consumers expect them.

## 12) Prover hardening
- Artifact verification: optionally add hash checks in `check_artifacts.sh`/startup to prevent stale/poisoned zkeys.
- Metrics: expand `/metrics` with Prometheus histograms/gauges for latency, inflight jobs, errors.
- CLI tooling (optional): add `go run ./cmd/verify-artifacts` to report circuit hash/artifact presence for CI gates.
- Runtime pinning: document `PROVER_RAPIDSNARK_BINARY` and Node versions for deployment manifests.

## 13) Test/QA plan (prove the zk flow)
- End-to-end script: start stack, ensure backend `/health` passes signer/FX checks, regenerate artifacts, deploy verifier, set `RM_PROVER_ENABLED=true` and automation flag as needed.
- Happy-path demo: (1) user connects wallet on Horizen testnet; (2) requests quote, submits `commitWithQuote`; (3) worker ingests commitment; (4) resolve market (manual trigger acceptable); (5) worker stores resolution ledger and requests proof; (6) prover generates proof; (7) API exposes proof on `/proofs`; (8) frontend shows proof and allows claim; (9) claim tx succeeds and ledger updates.
- Failure tests: stale FX blocks trade; expired quote rejected; wrong chain/address blocked; missing artifacts causes prover startup failure; CORS/connect-src misconfig surfaces dev warning.
- Coverage: backend tests for caps, quote persistence, resolution ledger, proof exposure; frontend tests for trading flow guards, proofs filters/CSV, positions dashboard, chart wiring; contracts/prover tests for updated circuit and verifier hash.



___

• Current state vs the happy-path:

  1. Connect & fund

  - Implemented: RelayerEscrow approve/deposit/withdraw; balanceOf + events; UI shows escrow with funding controls and blocks on wrong chain (Horizen testnet enforced in funding actions).
  - Tests: unit tests cover the chain guard; no full E2E flow yet.

  2. Market readiness

  - Implemented: backend auto-creates markets on first quote/commit (stubs a Market row if missing); Factory has predictMarketAddress, marketAddress, and getMarketParams views; worker backfills missing market_address each sync via factory view.
  - Requirement for market_id remains (must exist or be provided).

  3. Get price + caps

  - Implemented: QUOTE_V1 signing with caps; quoting works without a pre-known address (auto-create). Ensure env keys (pricing signer, factory/verifier/auth signer/oracle/wallet) are set.

  4. Confirm & submit

  - Implemented: quote→pricing_submit→CommitAuth→relayer commitWithAuthorization; ticket-size check; relayer retries with status/job id; contract enforces rake/ticket. Tests cover nonce replay/expiry/ticket size/maxCommitments/commit window/Committed event.

  5. Persist + notify

  - Implemented: backend stores commitments; returns tx hash, relayer status/job id, escrow balance; UI polls /trade/status and links to explorer for receipt; relayer retries in place (no persistent queue).

  6. Positions visibility & claims

  - Implemented: /positions + dashboard with claim; claim rebuilds Merkle path; contract has nextTicketId, commitmentsRoot, marketState, claim flow.
  - Added ingestion endpoints: /commitments/sync (relayer push), /settlements/ingest (prover/relayer push).
  - Pending: wire relayer/prover to call these ingest endpoints; UI doesn’t yet auto-refresh escrow after claim (it reloads positions/escrow on claim, but credited balance depends on relayer credit timing).



___
  - Market readiness: market_id still must be provided/known in DB. (We auto-create on-chain and backfill addresses, but we don’t mint a Market row for arbitrary IDs.)
___


• Here’s what’s implemented vs. still missing for each step of the “happy path”:

  1. Connect wallet

  - Implemented in frontend via wagmi; dashboard requires a connected address.

  2. Deposit to relayer escrow

  - Solidity supports it (RelayerEscrow.deposit/withdraw).
  - Frontend currently only displays escrow balance on /dashboard; there is no deposit/withdraw UI flow wired. Users cannot initiate deposits from the app yet. You’ll need a deposit form (approve + deposit) if you want this step in-app.

  3. Place a bet and debit escrow

  - Backend trade/commit routes exist; escrow debit happens in RelayerEscrow.commitOnBehalf (balance reduced, funds sent to market).
  - Frontend commit flow exists via useCommitWithQuote for on-chain commits; relayer-assisted commit flow is in API, but the UI for committing depends on your market pages (already present). No change needed for debit logic.

  4. Lock/settle and publish bundles

  - Backend has storage for commitments/settlements and the new /claim/bundles endpoint that assembles per-wallet bundles on demand.
  - Critical dependency: commitments + settlements must be ingested (worker/API commitments/settlements endpoints). Worker TODOs mention commitment ingestion is not wired by default. If you’re not persisting commitments and settlement snapshots, bundles won’t be served. Ensure the worker/API actually records
    commitments and settlement snapshots for each market.

  5. Dashboard “Claim” button submits claim(...) on-chain

  - Implemented: dashboard now fetches bundles (/claim/bundles) and calls the contract claim directly with user/ticketId/outcomeId/amount/salt/proof. UI shows errors/loading.
  - Not yet done: client-side sanity checks of leaf/root you mentioned earlier (the app currently trusts the backend bundle). Add those if you still want local verification.

  6. Funds go to the user wallet, not escrow

  - Implemented in RevealMarket.claim (transfers to user), and the dashboard assumes wallet receipt. Escrow balance is not incremented on claim.

  7. Protocol pool retains rake/surplus; unclaimed remain in market

  - Implemented: verifyAndSettle refunds surplus to the protocol pool; unclaimed liability stays in the market. No sweep exists.

  Security/UX gaps to address:

  - /claim/bundles is unauthenticated and keyed by a wallet query param; add auth/binding to the connected wallet to avoid leaking salts/bundles to arbitrary callers.
  - Worker ingestion needs to be active so commitments + settlements (and salts/leaf indices) are stored; otherwise bundles cannot be built.
  - Add a deposit/withdraw UI if you want users to fund escrow from the dashboard.
  - Optional: add leaf/root recomputation in the frontend before calling claim to guard against a bad backend bundle.
__
  -   - /claim/bundles is still unauthenticated (wallet query param). You should bind this endpoint to the authenticated wallet to avoid leaking salts/bundles.
  - Worker/ingestion must populate commitments + settlements for bundles to exist.
  - Deposit/withdraw also available in the market trade card (already present).
  - Tests not run here; please run:
      - cd backend/api && pytest
      - cd frontend && npm test && npm run lint
___

- Settlement signer not configured: RM_SETTLEMENT_SIGNER_PRIVATE_KEY is blank in .env.local and .env.production, so I can’t verify funding; fill it and ensure the address is funded on the test chain.

  - Next actions to unblock happy path: 1) align circuitHash (re-deploy verifier or roll prover back to the on-chain key); 2) set RM_SETTLEMENT_SIGNER_PRIVATE_KEY + RM_SETTLEMENT_RPC_URL and fund the signer; 3) restart worker/api with those envs so auto settlement can submit.



___

• RM_RAKE_MANAGER_ADDRESS is just the address of the on-chain RakeManager contract. It’s used whenever the backend/worker needs to know where rake configuration/ownership lives (e.g., on-chain rake overrides or admin flows). Today we keep it as 0x000…0 because we aren’t calling it in the happy-path flows; if you
  deploy a real RakeManager, set this env to its address so any on-chain ops that touch rake can point to the right contract.


› what does rake manager and why it is not deployed


• RakeManager is the on-chain contract that would hold rake config/ownership and let an admin update rake overrides. In this stack it’s optional—current flows hardcode rake in env (RM_RAKE_PERCENT) and don’t invoke on-chain rake updates, so we’ve left RM_RAKE_MANAGER_ADDRESS at 0x0 and haven’t deployed one. If you
  need on-chain rake governance later, deploy RakeManager and set the env to its address so API/worker/admin scripts can point to it.



___


deposit withdraw -> do I sponsor withdraw fee ? https://horizen-testnet.explorer.caldera.xyz/address/0x33c65aAC00aCE0b48876D9b87990E0c44F780708?tab=coin_balance_history

## Observation: testnet settlement guardrails

- The Solana price market (`0xCd70…1eF4`, marketId 13) remains in `Phase.Commit` with `commitmentsRoot=0` and `resultPosted=false`; commitDeadline is `1765933201` (future). The authorization signer is `0x38C574…5Fd`, and the oracle is `0x0F3d0f9274fA6AAEEbc493EdD44d2979BD75F369` (key in `scripts/generated/testnet_oracle_random_1764808324.txt`).
- `lock()` is `onlyOracle` and reverts with `CommitWindowClosed` until the deadline passes; you cannot prematurely lock with the settlement signer or relayer. Until lock runs, commitmentsRoot stays zero and proofs will fail TotalsMismatch checks.
- `postResult`/`verifyAndSettle` are also `onlyOracle`, so only the oracle key can advance the market, set the winning outcome, and accept Groth16 proofs. The settlement signer (`RM_SETTLEMENT_SIGNER_PRIVATE_KEY`, address `0x5B5A…A9D`) is not the oracle and cannot call these functions.
- The prover can emit Groth16 calldata, but without a real commitmentsRoot (lock) and resultPosted=true, `verifyAndSettle` will revert on-chain. Proofs generated against zero roots/liability are invalid by contract checks.
- To settle immediately for testing: either (a) wait for commitDeadline, then use the oracle key to `lock()`, regenerate proof with the real root/totals, `postResult(Yes)`, and `verifyAndSettle`; or (b) deploy a short-window test market where you control the oracle and repeat the flow. The current oracle ownership prevents off-schedule settlement—this is working-as-designed security.

### Privacy/anonymity notes
- Commit flow is hash-based: the on-chain commitment is a hash of (ticketId, outcomeId, amount, salt, user). The market contract only ever sees the hash until settlement; salts/amounts stay off-chain.
- Settlement uses Groth16: the proof attests to totals/liability/merkle root without revealing individual tickets. Public signals include commitmentsRoot, marketId, winningOutcomeId, totalEscrow, totalLiability, rakeBps, pools, and circuitHash—no per-user data.
- Claims require the user address + merkle proof for their leaf. Only the claiming user address is revealed on-chain at claim time; salts stay private, and non-claimed tickets remain sealed.
- Backend bundles (/claim/bundles) must stay wallet-scoped and authenticated to avoid leaking salts/paths. Frontend should validate the leaf/root locally if stronger assurances are needed.


• They can’t steal funds, even if they know every address:

  - The Merkle leaf binds the user address: leaf = hash(ticketId, outcomeId, amount, salt, user). The contract recomputes the leaf and sends the payout to the user passed in. If an attacker calls claim with their own address, the hash won’t match; if they call with your address, the funds still go to you.
  - A malicious caller could front‑run and pay gas to claim on your behalf (a “helpful” claim), but they can’t redirect the payout.

  What they can do if /claim/bundles is unauthenticated:

  - Enumerate addresses, fetch salts/paths, and learn position details (privacy leak).
  - Front‑run claims and burn your gas expectations (but still pay you).
  - Attempt spam/DoS with bogus calls.

  Mitigations:

  - Keep /claim/bundles wallet‑scoped: require a signature from the connected wallet (or authenticated session) and rate‑limit. Don’t serve bundles to arbitrary addresses.
  - Optionally validate leaf/root client‑side before calling claim to catch tampering.
  - If you want only the user to claim, add a msg.sender == user check (would require users to pay gas themselves).


› is this implemented? Keep /claim/bundles wallet‑scoped: require a signature from the connected wallet


• Explored
  └ Search claim/bundles in api
    Read trade.py

─ Worked for 8s ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

• Yes. /claim/bundles is wallet‑scoped and requires a signature:

  - The route expects wallet query param and X-Wallet-Signature header.
  - _verify_wallet_signature checks the signature against the wallet address; missing/invalid signatures return 401.
  - Bundles are fetched for that wallet only.

  So the endpoint already enforces a per‑wallet signature to avoid arbitrary bundle leakage.

• Your factory on Horizen testnet has 18 markets deployed. From the chain (factory 0xa7735E3790d58C737CB708b6a2E7CcFDa0afE7B8, nextMarketId=19):

  1 → 0x2D3A511b79623aE25e0F97fa31a9373a5933143D
  2 → 0xCeaC9436b4BC24847D02712817518c296Bf8b7E0
  3 → 0xa700fcBcfEb5f0e5d97Be1E57c84e3d8bb72Cd24
  4 → 0x238C49eD34f4cb53Dae368fe91BE34594C8cC100
  5 → 0x8905c20a610DE2BCDa9beCED0E5000e3A65D9CdA
  6 → 0x9332E16FD2B731E20eA40fB15c3b354cA3bB7316
  7 → 0x25bE1AEC69FC6399C02a5BabcDD09C8e398f3AD1
  8 → 0x0ed8B0cdB77e3ac3F374685c0725D07778D1e1d2
  9 → 0x7e82d9c77a0263373Dc2b770bf26B9AB2dE1596f
  10 → 0xcBEDbAeEA922fCd5c85AB286DBe8663db7e8D7Eb
  11 → 0xF4bF354b6aD13941a16a5bA1A4B3883cc6F390C3
  12 → 0xcaFD7080b64FE62Ef933D166223077aD55E2345d
  13 → 0xCd70B9be6E54968976A93D967E0340eC6E341eF4
  14 → 0x26BB3f2Dc826F2F7c903208711372606C71015CA
  15 → 0x6C685DD0E3215C0466798801697838995ba0aa17
  16 → 0xf2f53881Ec07B6B5b5E13cE61c60c0cd883F5B35
  17 → 0x5F456487de28b1c30e2b1420f3B26e0fF8131643
  18 → 0xBd49951FABB68d2109bD4862e0A3A3b7FE2B3D0C



  Endpoints not used by the UI (safe to ignore)

  - /pricing/submit isn’t called anywhere in the frontend.
  - /relayer/commitments and /relayer/settlements are relayer-only hooks; the UI should never hit them.
  - /commitments/sync and /settlements/ingest are for relayer/prover backfills, not normal buys.



• Here’s the definitive path the UI must follow to get addresses persisted, and what’s not needed:

  Required commit path

  - /pricing/preview → /pricing/quote (UI already calls these).
  - /trade/commit (must be called on every buy; this is the only place that deploys and stores market_address/onchain_market_id via _ensure_market_or_create → _maybe_create_market_onchain).
  - /trade/status (optional poll after commit; doesn’t affect persistence).

Why addresses are missing

  - A successful /trade/commit hasn’t run (or is failing). That’s the only write to markets.market_address/onchain_market_id.
  - If /trade/commit returns 5xx, check trade.market_create_failed logs; env must include RM_FACTORY_ADDRESS, RM_ORACLE_ADDRESS, RM_VERIFIER_ADDRESS, RM_RPC_URL, RM_RELAYER_BASE_URL, and RM_PRICING_SIGNER_PRIVATE_KEY.
  - If the request omits market_id or uses a different ID than the Polymarket event_id, _ensure_market_or_create can’t key the row.

  What to verify now

  1. In the browser network tab, confirm POST /trade/commit fires on the Buy button and returns 200.
  2. Tail API logs for trade.market_created (success) or trade.market_create_failed (failure) when you click Buy.
  3. Re-check the DB after a successful commit: select event_id, market_address, onchain_market_id from markets where market_address is not null; should show the new address.

  No duplicate/unused paths beyond the relayer/prover hooks noted above; the core flow is strictly preview → quote → commit.



## FLOW:
─ Worked for 2m 20s ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

• Here’s the end‑to‑end user flow you described, from escrow funding to payout, mapped to what’s actually wired today.

  - Fund escrow on /dashboard: user connects wallet on Horizen Testnet, approves ZEN to RelayerEscrow, then deposit(amount) is sent from their wallet. This is a normal on‑chain tx, so the user pays gas. (frontend/components/dashboard/DashboardClient.tsx, contracts/zen/src/RelayerEscrow.sol)
  - Open a market + click Buy YES/NO (0.1 ZEN):
      - The trade panel streams FX (/fx/zen-usd) and fetches a preview quote from /pricing/preview.
      - On CTA, it fetches a signed quote from /pricing/quote and submits /trade/commit.
      - Backend validates the quote, checks escrow balance, builds a CommitAuth, and calls the relayer.
      - Relayer calls RelayerEscrow.commitOnBehalf → transfers 0.1 ZEN from escrow to the market and calls RevealMarket.commitWithAuthorization. (frontend/components/markets/StakeQuoteCard.tsx, backend/api/app/routes/trade.py, contracts/zen/src/RelayerEscrow.sol, contracts/zen/src/RevealMarket.sol)
      - UI polls /trade/status and shows “Committed” once the relayer tx confirms.
  - Market ends (commit deadline passes):
      - Trading is blocked (commits_blocked_at, market status shows locked).
      - Worker/oracle ingests the resolved outcome off‑chain (Polymarket/Goldsky etc.) and marks the market resolved in DB.
  - Settlement + proofs (the critical bridge to claims):
      - Oracle/relayer locks commitments on‑chain with lockBatches (merkle roots + counts).
      - Oracle posts the winning outcome with postResult.
      - Prover generates Groth16 proofs (per batch).
      - Oracle submits verifyAndSettleBatched (or verifyAndSettle for 1 batch). Market phase becomes Settled on‑chain and roots/outcomes are fixed. (contracts/zen/src/RevealMarket.sol)
      - Relayer/prover pushes settlement snapshot to the API via /relayer/settlements or /settlements/ingest so the backend can build claim bundles.
  - Claim (user side):
      - On /dashboard, user clicks “Load payout data” → signs a message claim-bundles:<wallet>; frontend calls /claim/bundles with X-Wallet-Signature.
      - Backend returns per‑ticket bundles (root + proof + salt + amount).
      - UI verifies leaf/root locally, then sends RevealMarket.claim(...) from the wallet. User pays gas.
      - Payout transfers directly to the user wallet (not escrow). Positions update to claimed. (frontend/components/dashboard/DashboardClient.tsx, backend/api/app/routes/trade.py, contracts/zen/src/RevealMarket.sol)

  If any of these post‑market steps are missing (lock/settle/proof/settlement ingestion), positions will sit in “pending_resolution” and /claim/bundles will return nothing.

  If you want, I can diagram this as a sequence diagram or list the exact on‑chain txs + API calls in order.


› yes do  If you want, I can diagram this as a sequence diagram or list the exact on‑chain txs + API calls in order.


• I'll lay out a clear Mermaid sequence diagram showing how the user wallet, frontend, backend API, relayer, contracts, and oracle interact from deposit through trade, settlement, and claim. Then I’ll follow with an exact ordered list enumerating the API calls and on-chain transactions involved, highlighting gas
  payers, status polling, and alternative refund paths. This should give a full picture of the lifecycle the user experiences.

─ Worked for 1m 01s ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

• Here is the flow in both forms.

  Sequence diagram (end-to-end):

  sequenceDiagram
    participant U as User Wallet
    participant FE as Frontend
    participant API as API
    participant REL as Relayer
    participant ZEN as ZEN ERC20
    participant ESC as RelayerEscrow
    participant MKT as RevealMarket
    participant OPS as Oracle/Worker/Prover

    U->>FE: Open /dashboard (connect wallet)
    FE->>API: GET /positions?wallet=0x...
    U->>ZEN: approve(escrow, max)
    U->>ESC: deposit(amount)

    U->>FE: Open market page
    FE->>API: POST /pricing/preview
    FE->>API: POST /pricing/quote
    FE->>API: POST /trade/commit {quote_id}
    API->>REL: POST /commit (relayer payload)
    REL->>ESC: commitOnBehalf(user, market, auth, sig)
    ESC->>MKT: commitWithAuthorization(auth, sig)
    FE->>API: GET /trade/status?job_id=... (poll)
    FE->>API: GET /positions?wallet=0x...

    OPS->>MKT: lockBatches(roots, counts, relayerSig)
    OPS->>MKT: postResult(outcomeId)
    OPS->>MKT: verifyAndSettleBatched(proofs, signals)
    OPS->>API: POST /relayer/settlements (or /settlements/ingest)

    FE->>U: sign message "claim-bundles:0x..."
    FE->>API: GET /claim/bundles?wallet=0x... (X-Wallet-Signature)
    U->>MKT: claim(user, ticketId, outcomeId, amount, salt, proof)
    FE->>API: GET /positions?wallet=0x...

  Exact API calls + on-chain txs in order:

  1. GET /positions?wallet=0x... (dashboard loads escrow + positions)
  2. On-chain ZEN.approve(RelayerEscrow, max) (user pays gas)
  3. On-chain RelayerEscrow.deposit(amount) (user pays gas)
  4. POST /pricing/preview with {stake_zen, market_id, wallet_address, outcome_id, market_address}
  5. POST /pricing/quote with the same payload (returns signed quote)
  6. POST /trade/commit with {quote_id} (API builds CommitAuth, calls relayer)
  7. Relayer on-chain RelayerEscrow.commitOnBehalf(...) (relayer pays gas)
  8. Relayer on-chain RevealMarket.commitWithAuthorization(...) (relayer pays gas)
  9. GET /trade/status?job_id=... (poll until tx hash + confirmed)
  10. GET /positions?wallet=0x... (status shows committed/locked)
  11. On-chain RevealMarket.lockBatches(roots, counts, relayerSig) (oracle/ops)
  12. On-chain RevealMarket.postResult(outcomeId) (oracle/ops)
  13. On-chain RevealMarket.verifyAndSettleBatched(proofs, signals) (oracle/ops)
  14. POST /relayer/settlements or POST /settlements/ingest (ops push settlement snapshot so claims are possible)
  15. GET /claim/bundles?wallet=0x... with X-Wallet-Signature: <sig>
  16. On-chain RevealMarket.claim(user, ticketId, outcomeId, amount, salt, merkleProof) (user pays gas)
  17. GET /positions?wallet=0x... (shows settled/claimed)

  Optional after claim:

  - On-chain RelayerEscrow.withdraw(amount) to pull any remaining escrow balance (user pays gas).

  If you want, I can add a simplified “user-only” version that omits the relayer/settlement internals.


________

• Here’s a concise go‑live checklist for the full flow, grouped by component.

  Contracts / Chain

  - Deploy latest MarketFactory, RelayerEscrow, ProtocolPool, RevealMarket implementation, Verifier.
  - Confirm factory config:
      - globalRakeBps, authorizationSigner, protocolPool, relayerEscrow, verifier, circuitHash.
  - Run contracts/zen/scripts/check_circuit_hash.sh to confirm verifier hash matches prover artifacts.
  - Create markets via contracts/zen/scripts/create_market.sh and ingest into backend.

  Backend (API + DB)

  - Reset DB (fresh start), apply migrations (merged 0001).
  - Verify API envs:
      - RM_DATABASE_URL, RM_REDIS_URL, RM_RELAYER_BASE_URL, RM_RELAYER_WEBHOOK_SECRET
      - RM_PRICING_SIGNER_PRIVATE_KEY, RM_PRICING_QUOTE_TTL_SECONDS
      - RM_CORS_ALLOW_ORIGINS, RM_TRUSTED_HOSTS
  - Bring up API + Postgres + Redis; confirm /health returns ok.

  Worker / Oracle / Settlement

  - Set worker envs:
      - RM_RPC_URL, RM_AUTO_LOCK_BATCHES_ENABLED=true
      - RM_LOCK_BATCHES_USE_RELAYER=true or set RM_SETTLEMENT_SIGNER_PRIVATE_KEY
      - RM_PROVER_ENABLED=true, RM_AUTO_SETTLEMENT_ENABLED=true
      - RM_AUTO_SETTLEMENT_TX_ENABLED=true, RM_SETTLEMENT_RPC_URL (or RM_RPC_URL)
  - Confirm worker is ingesting resolutions and writing winning_outcome_id.

  Relayer

  - Configure:
      - RELAYER_PRIVATE_KEY, RELAYER_RPC_URL
      - RELAYER_API_BASE_URL (points to API), RELAYER_WEBHOOK_SECRET (matches API)
  - Confirm relayer endpoints accept:
      - /commit, /lock-batches, /claim, /settlements/ingest

  Prover

  - Ensure prover/circuits/build has current artifacts + keys.
  - Start prover service and verify /healthz.

  Frontend

  - Set NEXT_PUBLIC_API_BASE_URL, NEXT_PUBLIC_PRICE_STREAMER_URL.
  - Confirm /dashboard loads positions and escrow balance.
  - Confirm market page streams FX + quotes and can commit.

  End‑to‑End Validation (manual)

  - Deposit ZEN to escrow.
  - Buy YES/NO with 0.1 ZEN and confirm relayer tx.
  - Wait for market close and resolution ingest.
  - Confirm lockBatches + postResult + verifyAndSettleBatched txs appear.
  - Call /claim/bundles, submit claim(...), verify payout and UI status “Claimed”.
