# Backend MVP Checklist

These are the only backend tasks blocking the MVP launch. Defer everything else until these land.

## 0. Signed pricing + quote storage
- Keep the API signing ABI-packed quotes that match `RevealMarket.commitWithQuote` (`QUOTE_V1`, chainid, market, wallet, outcome, stake_wei, fx_scaled, expiry, quoteId) and reject requests missing those fields.
- Add durable quote persistence (status, expiry, consumed_at) instead of best-effort Redis so we can audit/replay-protect even if Redis evicts.
- Expose a health/smoke check for pricing signer envs (`RM_PRICING_CHAIN_ID`, signer key/address) and fail fast when misconfigured.

## 1. AI summary provenance
- Persist every AI-generated summary (model, prompt hash, retrieval context, requested/checked timestamps) in Postgres.
- Expose the summary history via `/markets/{event}` and include the latest metadata in `/markets` responses so auditors can trace narrative evolution.

## 2. Resolution ledger
- Store resolution payloads (condition ID, payouts, winners, oracle/question IDs, block number, block timestamp, tx hash) in Postgres + Redis.
- Return this data from `/markets`, `/markets/{event}`, and `/proofs` without needing to hit upstream APIs.

## 3. On-chain mirroring & automation
- Stream MarketFactory events (MarketCreated, RakeConfigured, guardian updates) into Postgres/Redis so rake + address data never drifts.
- Add an optional settlement automation loop that queues on-chain settlement transactions (or alerts ops) once payouts finalize, with duplicate suppression + retry logging.

Ship these three items and the backend will meet MVP expectations for provenance, settlement integrity, and ops readiness.

## 4. Bet caps (off-chain + future on-chain)
- Enforce per-bet cap (0.1 ZEN), per-user-per-market cap, and per-market ZEN cap at the API layer; surface limits in responses.
- Mirror caps in hedger risk checks so oversized commits never hedge.
- Add a TODO for on-chain enforcement (maxTicketStake, maxUserStakePerMarket) to close the loop in a later contract upgrade.

## 5. CORS/FX hardening
- Add a smoke test to ensure `/pricing/fx` responds with configured CORS origins (RM_CORS_ALLOW_ORIGINS) and flags stale/fallback FX.
- Surface a health warning when FX feeds fall back or when streamer/API origins are missing, so frontend SSE/history calls don’t get blocked.
- Keep pricing signer chain/env vars aligned to Horizen Testnet defaults (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`) and warn when mismatched.

## 6. API security hardening
- Critical – Mutation endpoints are unauthenticated. backend/api/app/main.py:3529-3609 exposes POST/PATCH market upserts with no auth despite being operational controls; anyone can create/modify markets and poison caches. Similar unauthenticated operational surfaces include /pricing/quotes/{id}, /treasury/snapshots, /proofs, /clob/orderbook, and /markets/onchain (various routes around lines 2513-2590, 2974-3036, 3164-3270, 3497-3526). These should be gated (API key/JWT/internal network) or removed from public exposure.
- Critical – Pricing signer will sign arbitrary contracts/outcomes. In pricing_quote (backend/api/app/main.py:2140-2311) the service accepts any market_address, outcome_id, and even non-existent market_id; it only blocks if a known market is already settled. An attacker can request quotes for their own contract/outcome and receive a valid signer signature, bypassing caps by inventing event IDs. The quote flow needs an allowlist: require the market to exist, match the stored factory address/outcome count, and refuse unknown/settled or mismatched addresses before signing.
- High – Rate limiting is trivial to bypass. RateLimitMiddleware trusts the first X-Forwarded-For/X-Real-IP header from the client (backend/api/app/rate_limit.py:162-174) and uses an in-process memory fallback, so a client can spoof headers or fan out across workers to evade limits and flood quote creation (which writes to Postgres). Pin the trusted proxy list or read scope['client'], and keep Redis as the source of truth for counters.
- High – Caps/quotas rely on untrusted identity. The per-user cap logic in pricing_quote/pricing_submit (backend/api/app/main.py:2188-2299, 2330-2405) trusts the client-supplied user_id with no linkage to the wallet or session, so an attacker can exhaust another user’s allowance or bypass their own by rotating IDs. Derive the identifier from authenticated context (wallet signature/session) and ensure it matches the quote payload.
- Medium – Information exposure via diagnostics. Health and diagnostic routes return sensitive internals (schema revision, pricing signer status, cache stats, worker latencies) and treasury/proof/quote data (backend/api/app/health.py:36-208, backend/api/app/main.py:2513-2590, 3164-3270). Prometheus /metrics is also exposed without auth. Restrict these to internal networks or add auth + redaction before MVP.
