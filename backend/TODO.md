# Backend MVP Checklist

These are the only backend tasks blocking the MVP launch. Defer everything else until these land.

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
- Enforce per-bet cap (100 ZEN), per-user-per-market cap, and per-market ZEN cap at the API layer; surface limits in responses.
- Mirror caps in hedger risk checks so oversized commits never hedge.
- Add a TODO for on-chain enforcement (maxTicketStake, maxUserStakePerMarket) to close the loop in a later contract upgrade.

## 5. CORS/FX hardening
- Add a smoke test to ensure `/pricing/fx` responds with configured CORS origins (RM_CORS_ALLOW_ORIGINS) and flags stale/fallback FX.
- Surface a health warning when FX feeds fall back or when streamer/API origins are missing, so frontend SSE/history calls don’t get blocked.
