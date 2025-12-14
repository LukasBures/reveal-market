# Reveal Market Data Infrastructure

The backend is the heartbeat of Reveal Market’s investable ecosystem. It transforms third-party liquidity into institutional-grade intelligence, ensuring every chart, fee accrual, and settlement insight backing our treasury is verifiable in real time.

## Two Services, One Mission

| Component | Investor Benefit |
| --- | --- |
| **Market API** | Surfaces curated markets, stats, and settlements through a high-availability FastAPI layer backed by Redis caching, structured logging, and Prometheus metrics. Investors see the same latency and transparency they expect from Tier-1 exchanges. |
| **Ingestion & On-Chain Worker** | Continuously ingests Polymarket and Conditional Tokens data, reconciles it with our PostgreSQL source of truth, and sends heartbeats so ops can verify freshness. |
| **Price Streamer** | Separate FastAPI service (see `streamer/`) that handles live Polymarket CLOB + FX streaming via SSE/WS. The frontend calls `/stream`/`/stream/ws` with explicit `assets_ids` (clobTokenIds) from the market-detail API for the fastest live books/trades; no auto-discovery is used. |

Shared SQLAlchemy models, cache helpers, and logging modules guarantee that both services speak a single data dialect—which is critical for compliance reviews and long-term valuation work.

> **Reality check**
>
> - The bundled `prover` service now boots a Groth16 pipeline (Circom witness generation + `rapidsnark`) and halts startup if the artifacts under `prover/circuits/build` are missing. Always refresh the proving/verifying keys via `prover/circuits/generate_keys.sh` before marketing the stack as zk-auditable.
> - Worker ingestion targets Polymarket’s Gamma API; when the upstream dataset returns `image_url = null`, the frontend falls back to deterministic placeholders. Populate `extra_data.image_url` via the worker once you negotiate richer feeds.
> - All environments, including local Docker, rely on the live backend—mock API toggles have been removed from the frontend.

## Proof Points For Stakeholders

- **Deterministic data lineage** – Every market travels through an audited pipeline: upstream fetch → repository upsert → cache tagging → API exposure. The cycle produces traceable logs and metrics so diligence teams can replay any event.
- **Heartbeat-driven reliability** – Workers advertise liveness via Redis keys with TTLs. If a heartbeat is missed, alerting fires before stale data reaches investor dashboards.
- **Smart economics tracking** – API responses expose rake basis points, settlement hashes, and on-chain identifiers. This enables LPs to model expected yield and for treasury to forecast protocol revenue.
- **Security-first delivery** – Migrations run automatically, containers execute as non-root users, and optional on-chain helpers remain manual-only so production workers never sign transactions without explicit operator action.
- **Perimeter controls baked in** – Trusted-host filters, configurable CORS allowlists, and CSP/HSTS/COOP headers ship with the API. Docker health checks call native Python probes rather than brittle shell scripts.
- **Network defaults (Horizen Testnet)** – Default chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, explorer `https://horizen-testnet.explorer.caldera.xyz`. Keep `RM_PRICING_CHAIN_ID` aligned when signing quotes and configure on-chain addresses per environment.

## Horizen Indexing via Goldsky

Horizen events (MarketFactory deployments, Conditional Tokens resolutions, rake changes) can now be sourced from Goldsky-managed subgraphs. Provide `RM_GOLDSKY_SUBGRAPH_URL` + `RM_GOLDSKY_API_KEY` and the worker will prefer GraphQL lookups for payout vectors before falling back to direct RPC calls. This gives ops teams fast, filterable history without running dedicated indexers, and it unlocks the roadmap items around persistent resolution ledgers, Horizen ZEN testnet monitoring, and investor-friendly audit exports.

When Goldsky isn’t configured the previous RPC path remains intact, so staging environments can toggle the feature independently.

## Upcoming Enhancements

The roadmap prioritizes capabilities that increase investor trust:

1. **Resolution persistence** – Hydrate on-chain payout vectors into the database so `/resolution` responses remain fast and auditable, even during RPC turbulence.
2. **Schema safety for worker-first deployments** – Allow the worker to enforce Alembic head state, preventing schema drift when API nodes are temporarily offline.
3. **Polymarket resilience** – Shared retry logic and metrics across both services, giving institutional partners real SLAs on data freshness.
4. **Horizen ZEN testnet option** – Spin up a regulated sandbox for exchanges to trial the stack with real capital on a whitelisted network.

These milestones ladder up to the same thesis: reliable data fuels confident liquidity.

## Service-Level Docs

- [`backend/api/README.md`](./api/README.md) – FastAPI runtime, security headers, health check details, and env vars.
- [`backend/worker/README.md`](./worker/README.md) – Polymarket ingest, cache invalidation, on-chain automation, and worker config.
- Signed-quote flow: the API signs ABI-packed pricing quotes (bound to chain id, market, wallet, outcome, stake wei, FX 1e8, expiry, quoteId) and the `RevealMarket.commitWithQuote` entrypoint enforces them on-chain. Set `RM_PRICING_CHAIN_ID` + `RM_PRICING_SIGNER_PRIVATE_KEY` and expose `PRICING_SIGNER_ADDRESS` in deployments.

## Partner Takeaways

- **Integration optionality** – Exchanges can embed only the API, enterprises can operate both API and worker in their own VPC, or sovereign partners can tap our managed service. The shared codebase ensures consistency across every deployment.
- **Observability built in** – Audit teams receive structured logs (request IDs, cache hit ratios, fetch latency) and Prometheus series capturing every pipeline stage.
- **Token-aligned upside** – Because protocol fees are captured at the API layer and mirrored on-chain, governance decisions about rake, settlement cadence, and new markets create tangible upside for future token holders.

## Operational Hardening

- Cache paths now explicitly bypass Redis when it is unavailable. Endpoints log the bypass, skip tag pollution, and keep request metrics accurate instead of claiming a “cache miss” that never wrote to Redis.
- Category caches only register tags when a payload is actually written, preventing dangling invalidation sets during oversized/offset queries.
- Resolution persistence in the worker was simplified to drop unused state flags, keeping the sync loop lean while still emitting cache payloads for downstream services.

To learn how the backend can power your venue, reach out through the site contact form or via [X](https://x.com/RevealMarket). We are actively onboarding exchanges, OTC desks, and liquidity programs who want transparent exposure to the next generation of prediction markets.

## Local Validation (Python 3.12 + uv)

Reproducible tests are part of the trust story. Backend services now target Python 3.12, and the `make test` target simply shells into `backend/run_tests.sh`, which prefers `uv run` so every environment obeys the same `uv.lock`.

1. **Sync per-service environments (once):**

   ```bash
   uv sync --project backend/api --extra dev --no-install-project
   uv sync --project backend/worker --extra dev --no-install-project
   ```

2. **Keep the envs up-to-date:**

   ```bash
   uv sync --project backend/api --extra dev --no-install-project --frozen
   uv sync --project backend/worker --extra dev --no-install-project --frozen
   ```

3. **Run the consolidated test suite:**

   ```bash
   make test          # or ./backend/run_tests.sh
   ```

Both `.venv` directories stay ignored by git. `uv` keeps them consistent with the `pyproject.toml` + `uv.lock` definitions, so CI, local shells, and the Docker images all share the exact dependency graph.

`./backend/run_tests.sh` automatically sets `-n 4` for every pytest invocation (API, shared modules, worker) so local runs match CI’s concurrency. Override via `PYTEST_WORKER_COUNT=<n>` if you’re on a smaller dev box or want to test with extra workers.

## Deployment Runbook (API + Worker)

- **Prereqs**: Postgres + Redis reachable; run `backend/migrations` before boot if you disable lifespan migrations.
- **Env**: Set `RM_DATABASE_URL`, `RM_REDIS_URL`, Polymarket endpoints (`RM_POLYMARKET_API_BASE`, `RM_POLYMARKET_TIMEOUT_SECONDS`, rate limits), and FX feed URLs. For Docker compose, copy `.env.example` and adjust addresses.
- **Migrations**: Default lifespan runs migrations on boot. For explicit smoke, run `python -m app.database` or `backend/run_tests.sh` (includes a startup smoke). If migrations fail, the service exits non-zero.
- **Health / smoke**: After deploy, hit `/healthz` (API) and `/healthz` (worker via Docker healthcheck). Expect `status=ok`, Redis/DB/Polymarket `ok`, and fresh heartbeats. Logs emit `service.configuration` and `markets.cache.refresh.start` on boot.
- **Cache warmup**: Optional—call `/markets?limit=20` and `/pricing/fx` to prime caches/CDN. Heartbeat dashboards at `/healthz/heartbeats`.
- **TLS/proxy**: Terminate TLS at the ingress/proxy (e.g., Caddy in `docker/caddy/Caddyfile`). API/worker remain HTTP internally; set `ALLOWED_HOSTS`/CORS as needed.

## Resolution + Commit Halting Signals

- Markets now carry `resolution_status` (`final`, `pending_resolution`, `disputed`), `resolution_reason`, and `commits_blocked_at` on the core `markets` table. Worker ingestion sets these flags from Gamma and locks commits when upstream marks a market pending or disputed.
- The API enforces a configurable cutoff window (`RM_COMMIT_CUTOFF_SECONDS`, default 900s) before `closes_at` to halt new quotes/commits. Pending/disputed markets or those inside the cutoff return `400` errors with a descriptive `detail`.
- Frontend surfaces the flags as “Waiting for resolution” / “Disputed” and disables commit buttons; positions payloads now echo the flags so wallets can show claim readiness accurately.
- Settlement automation wiring: enable `RM_PROVER_ENABLED=true`, `RM_AUTO_SETTLEMENT_ENABLED=true` to request proofs; set `RM_AUTO_SETTLEMENT_TX_ENABLED=true` plus `RM_SETTLEMENT_SIGNER_PRIVATE_KEY`, `RM_SETTLEMENT_RPC_URL` (or `RM_RPC_URL`) and optional `RM_SETTLEMENT_GAS_PRICE_GWEI`/`RM_SETTLEMENT_MAX_PRIORITY_FEE_GWEI` to auto-submit `verifyAndSettle` once proofs are ready. Proof receipts now store the raw `proof` + `publicSignals`; settlements persist tx hash/block/submitted_at.

## Test Chain Runbook (Settlement E2E)

- Fund the settlement signer (matches `RM_SETTLEMENT_SIGNER_PRIVATE_KEY`) with testnet gas + ZEN for fees.
- Start prover with artifacts mounted (`prover/circuits/build/*`), set `RM_PROVER_ENABLED=true` and `RM_AUTO_SETTLEMENT_ENABLED=true`.
- Enable tx submission: `RM_AUTO_SETTLEMENT_TX_ENABLED=true`, `RM_SETTLEMENT_RPC_URL` (or reuse `RM_RPC_URL`), optional `RM_SETTLEMENT_GAS_PRICE_GWEI`/`RM_SETTLEMENT_MAX_PRIORITY_FEE_GWEI`.
- Monitor logs/metrics: `worker.proof.*` for proof retries/failures, `worker.settlement.*` for tx submissions/failures; ensure circuit hash/verifier on-chain match the prover outputs.
- Dry-run: pick a seeded market, verify `circuitHash` matches, and watch `settlements` rows for `proof_status=generated` and `settlement_tx_hash` populated after submission; claims should open once tx confirms.

## Logging Consistency

Each service now bootstraps a production-grade logger at process start. The format matches `timestamp | LEVEL | logger | file:line | event | message | request_id=<value>` so API, worker, and scripts emit comparable lines. Control verbosity with `LOG_LEVEL`, and opt into rotating files by setting `LOG_TO_FILE=true` (optional knobs: `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`). All logs still stream to stdout for container aggregation, ensuring Docker/Kubernetes collectors see exactly the same structure across services.
