# Reveal Market MVP – Implementation Summary

This MVP ships an end-to-end, mainnet-ready stack for fixed-size commit/reveal markets on Horizen Mainnet (chain id `26514`). It includes FastAPI backend + worker, relayer, streamer, prover, frontend, and Solidity contracts. Circuits/keys live in `prover/circuits/build`; verifier/circuit hash must match everywhere.

## What Works Today
- **Contracts (Zen workspace)**: MarketFactory deploys clone-based markets (fixed ticket, rake, caps). RelayerEscrow holds collateral and forwards commits with backend-signed authorizations. RevealMarket stores commitments, locks Poseidon batch roots (BATCH_SIZE=256, MERKLE_DEPTH=8), verifies Groth16 proofs (`verifyAndSettleBatched` or single-batch), pays claims directly to users, and enforces protocol cap via ProtocolPool. Refund + pause paths exist.
- **Backend API**: Async FastAPI with Redis caches for markets/categories/suggest/resolutions. `/pricing/quote` signs QUOTE_V1 (FX pulled from streamer), `/trade/commit` builds CommitAuth and forwards to relayer with Redis queue fallback, `/positions`/`/claim/bundles` surface claims, `/proofs` lists prover receipts. Health/metrics expose DB/Redis/Polymarket/pricing/circuit checks; migrations run on startup.
- **Worker**: Async ingestion of Polymarket Gamma `/events` with retries/backoff and optional Goldsky resolutions. Upserts normalized tables, invalidates/warms caches, publishes heartbeats/batch stats, builds Poseidon Merkle data, and can enqueue prover jobs when configured.
- **Relayer**: FastAPI + Web3 service with durable queue (SQLite or Postgres) for `commit`, `claim`, and `lockBatches`. Fee bumps and retries are built-in; health reports RPC/balances/owner, metrics expose queue depth/outcomes.
- **Streamer**: FastAPI SSE/WS for CLOB data + FX. DataStreamer ingests Polymarket WS/REST (+optional RTDS), caches/publishes ticks/history via Redis; PriceStreamer ingests Binance WS with REST fallback and staleness guards. Goldsky subgraph proxies are exposed over HTTP/WS.
- **Prover**: Go microservice wrapping rapidsnark + Circom witness generation (Node or C++). No mock mode—startup fails if artifacts are missing or invalid. `/healthz` + `/metrics` show readiness and circuit hash; proof endpoint returns calldata/public signals/metadata with optional SSE.
- **Frontend**: Next.js 15 App Router site (marketing + trading + dashboard + proofs). Uses backend fetchers with cache tags, streams prices/FX from streamer (WS/SSE with HTTP fallback), enforces chain guards, and drives the quote → commit → status polling flow. Dashboard surfaces escrow/positions/claims; `/proofs` lists receipts with filters.

## Typical User Journey (Mainnet)
1. Fund escrow (approve + deposit ZEN to RelayerEscrow).
2. Browse markets (`/markets`, `/markets/{event}`) served from cached API data.
3. Request `/pricing/preview` (optional) then `/pricing/quote` (FX from streamer, caps enforced).
4. Submit `/trade/commit` → relayer queue → on-chain `commitOnBehalf` (`commitWithAuthorization` inside). Rake goes to ProtocolPool.
5. After commit deadline, oracle (or relayer) calls `lockBatches`, posts result, requests proofs from prover, and settles via `verifyAndSettleBatched` (or single-batch). ProtocolPool covers shortfall up to cap.
6. Claims: wallets call `claim` directly (or relayed claim via API → relayer). Dashboard shows claimable tickets; `/proofs` surfaces receipts.

## Defaults & Alignment
- Chain: Horizen Mainnet (`26514`), RPC `https://horizen.calderachain.xyz/http`, explorer `https://horizen.calderaexplorer.xyz`.
- Caches: Redis JSON with tag-based invalidation; resolved markets expire 12h after `resolved_at`.
- Caps: server-side caps on stake per quote/user/market; ticket size fixed per market in contracts.
- Circuit/hash: `prover/circuits/build/settlement_hashes.json` is the source of truth; keep on-chain verifier, backend envs, and frontend displays aligned.

## Operational Notes
- Services expose `/healthz` and `/metrics` (Prometheus). Worker/streamer/relayer/prover emit structured logs with request IDs; API/worker run Alembic migrations on startup.
- Auth is minimal by default; production must add auth/allowlists for mutation/admin routes and set secrets (`RM_RELAYER_WEBHOOK_SECRET`, prover shared secret, streamer access/control tokens).
- Artifact management: generate via `prover/circuits/generate_keys.sh` or fetch hosted archive (`PROVER_ARTIFACTS_URL` + SHA256). Docker images expect `prover/circuits/build` mounted/readable.

## Validation
- Backend: `./backend/run_tests.sh` (pytest -n 4, includes schema/health/cache tests).
- Frontend: `npm run lint && npm run test && npm run build` (or `frontend/run_tests.sh`), optionally with `FRONTEND_REQUIRE_API=true`.
- Contracts: `contracts/run_tests.sh` (runs `zen` then `polygon` workspaces; `run_local.sh full` adds fuzz/coverage).
- Streamer/Relayer/Hedger/Prover: `./run_tests.sh` in each service or `go test ./prover/...` for prover.

This MVP is wired end-to-end for zk-proof settlement on mainnet; remaining work is tracked in the service-specific `TODO.md` files.
