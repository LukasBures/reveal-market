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




• Here’s a workable MVP flow that matches the current stack (relayer + fixed-ticket commitWithAuthorization) and gives users something to see after they trade.

  Happy-path flow

  1. Connect & fund
      - User connects wallet (Horizen testnet enforced).
      - Approve + deposit ZEN into RelayerEscrow. UI shows escrow balance. (Contract path: approve(ZEN, escrow), then escrow.deposit.)

  2. Market readiness
      - If the market isn’t deployed yet, backend/worker/relayer creates or predicts it via MarketFactory and stores market_address against the event. The market will be created only when user click buy/trade it will not hide/disallow trading. It should not matter if the market is deployed or not, only for the first bet/trader it has to create that market before the user will create trade.

  3. Get price + caps
      - UI requests /pricing/quote with {wallet_address, market_id, market_address, outcome_id, stake_zen}.
      - API signs QUOTE_V1, applies caps, returns quote_id, expiry, signer, chain_id, caps, FX timestamp.
  
  4. Confirm & submit
      - Client POSTs a “trade” action (backend route) with quote_id (and optionally the full quote for drift guard).
      - Backend calls /pricing/submit to mark the quote consumed and verify signature/FX drift.
      - Backend derives CommitAuth (commitment hash, nonce, expiry) and calls relayer commitOnBehalf (or enqueues it) → relayer sends commitWithAuthorization to the market. Ticket size should match the quoted stake (for MVP keep ticketSize = 0.1 ZEN).
  
  5. Persist + notify
      - On success, backend stores: quote_id (consumed), tx_hash, market_id, user_address, outcome_id, amount_wei, ticket_hash/leaf, merkle index (if known).
      - Response to UI: {txHash, quoteId, marketId, outcomeId, stakeZen, entryFx, potentialPayoutZen, status: "committed"} and updated escrow balance (escrow debits ticket).
  
  6. Positions visibility
      - Expose /positions?wallet=… (or session-bound) that returns live commitments with: market/title/outcome, stake, entry FX, quote_id, tx_hash, status (pending/committed/settled), potential win, and whether claimable.
      - After resolution + proof ingestion, relayer runs claim and credits escrow; positions entry flips to claimed and shows credited amount.
      - User can withdraw from escrow (escrow.withdraw) to wallet.

  What the user sees in the UI

  - After submitting: tx hash (relayer commit), stake, outcome, implied odds, and a “position added” row.
  - In Positions: list of open tickets with stake, entry price/FX, potential payout, market status. Show “claimable” when the backend/worker marks it so; show credited amount after claim. Escrow balance visible for withdraw.
  - Errors that block trading: missing market_address, wrong chain, stale FX, cap exhausted, quote expired/consumed.

  Key plumbing needed

  - A backend “trade” endpoint to consume quotes + call relayer; mark quotes consumed.
  - Ensure markets have market_address (predict/create if missing) before enabling trade.
  - Persist commitments in Postgres (we already have commitments table) when relayer tx lands.
  - Positions API + minimal UI to render them, plus escrow deposit/withdraw UI.
  - Keep ticket size aligned with quoted stake (MVP: fix at 0.1 ZEN to match UI cap and relayer ticketSize).