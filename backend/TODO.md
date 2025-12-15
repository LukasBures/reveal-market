# Backend MVP + Hardening Checklist

The backend already runs the API, ingestion worker, quote ledger, cache priming, and prover hooks. These tasks close the remaining gaps for auditability, safety, and exchange-readiness.

## 0. Signed pricing + quote ledger (must ship)
- Persist quotes durably in Postgres (`quotes` table) with statuses (`issued`/`consumed`/`expired`), requester identity, FX snapshot, and expiry timestamps; stop relying on Redis-only TTLs.
- Enforce quote issuance against known markets: require `market_id` exists, matches stored factory address + outcome count, is not settled/blocked, and reject arbitrary addresses/outcome IDs before signing.
- Add readiness smoke for signer config (RM_PRICING_CHAIN_ID, RM_PRICING_SIGNER_PRIVATE_KEY, PRICING_SIGNER_ADDRESS) and fail fast when misconfigured; surface signer status in `/health` with clear degraded/error states.
- Make replay protection provable: expose quote lookups + audit endpoint gated by auth so ops can reconcile quotes vs commits; sweep expired quotes on an interval and mark consumed in a transaction inside `pricing_submit`.

## 1. AI summary provenance
- Persist every summary in Postgres with `model`, `prompt hash/template`, `source docs`, `requested/attempted/checked_at`, and `status` (generated/failed/fallback); include the rendered text.
- Expose history per market via `/markets/{event}` and surface the latest summary metadata in `/markets` list payloads; include `summary_source`/`summary_model`/`summary_generated_at`.
- Add DLQ/retry metrics for `summary_worker`, plus health warnings when summaries are stale or when the provider falls back to the deterministic template.

## 2. Resolution ledger + receipts
- Store payout vectors in Postgres + Redis (`resolutions`, `resolution_snapshots`) with condition id, question/oracle ids, block number/ts, tx hash, payouts array, and `resolution_source`.
- Return this ledger in `/markets`, `/markets/{event}`, and `/proofs` without querying upstream; invalidate caches on refresh.
- Cache prover receipts keyed by market/condition and surface them in `/proofs`/`/markets/{event}`; include circuit hash/verifier address alignment checks.

## 3. On-chain mirroring & automation
- Mirror MarketFactory/ProtocolPool/RelayerEscrow events into Postgres (MarketCreated, RakeConfigured, guardian/owner updates, factory hooks) and expose the latest rake/liability caps via the API.
- Optional settlement automation: queue prover requests + `verifyAndSettle` tx submission with idempotency, duplicate suppression, and retry/backoff; surface per-market automation status + last error.
- Add operator alerts/webhooks when proofs fail, automation pauses, or verifier/circuit hash mismatch is detected.

## 4. Bet caps + identity alignment
- Enforce per-bet (0.1 ZEN), per-user-per-market, and per-market caps in `pricing_quote`/`pricing_submit`; return limits in responses so the frontend can show them.
- Derive user identity from authenticated context (wallet signature or session) instead of trusting `user_id` input; tie the identity to the quote digest and submission.
- Mirror caps into hedger risk checks (shared settings) so oversized commits are rejected before hedging; document the future on-chain enforcement path (`maxTicketStake`, `maxUserStakePerMarket`).

## 5. CORS/FX hardening
- Add health/log warnings when streamer/API origins or CORS lists are missing/misaligned; `/pricing/fx` should refuse to start if `RM_CORS_ALLOW_ORIGINS` is unset in prod.
- Make FX drift checks explicit: reject quotes when FX is stale or when drift exceeds configured tolerance; surface fallback source (Binance REST/CryptoCompare) in health.
- Tests: smoke that `/pricing/fx` honors CORS, stale detection, and streamer host overrides; ensure Horizen Testnet defaults stay aligned (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`).

## 6. API security hardening (critical)
- Gate mutation endpoints (`/markets` POST/PATCH, `/pricing/quotes/{id}`, `/treasury/snapshots`, `/proofs`, `/clob/orderbook`, `/markets/onchain`) with API key/JWT/internal network; add authn/role checks and redact sensitive fields in responses.
- Fix rate limiting: trust proxy list or `scope['client']`, remove in-process counters, and enforce Redis-backed limits for quote creation; add tests around header spoofing.
- Lock down diagnostics: restrict `/metrics`, `/health`, treasury/proof/quote debugging routes to internal auth; redact schema revisions/signers when unauthenticated.

## 7. Async + performance hygiene
- Audit any remaining blocking calls (CLOB clients, on-chain helpers) and offload to threads or async implementations; trace slow spans.
- Remove `shared/*` mypy ignores after publishing `py.typed` and stabilizing type hints; keep inline docs current.
- Add load tests for cache bypass modes (Redis down) to ensure endpoints stay non-blocking and logs/metrics remain accurate.
