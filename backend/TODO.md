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
