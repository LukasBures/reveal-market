# Reveal Market Data Infrastructure

The backend is the heartbeat of Reveal Market’s investable ecosystem. It transforms third-party liquidity into institutional-grade intelligence, ensuring every chart, fee accrual, and settlement insight backing our treasury is verifiable in real time.

## Two Services, One Mission

| Component | Investor Benefit |
| --- | --- |
| **Market API** | Surfaces curated markets, stats, and settlements through a high-availability FastAPI layer backed by Redis caching, structured logging, and Prometheus metrics. Investors see the same latency and transparency they expect from Tier-1 exchanges. |
| **Ingestion & On-Chain Worker** | Continuously ingests Polymarket and Conditional Tokens data, reconciles it with our PostgreSQL source of truth, sends heartbeats, and can optionally originate on-chain markets via MarketFactory. This keeps treasury projections synchronized with on-chain cash flows. |

Shared SQLAlchemy models, cache helpers, and logging modules guarantee that both services speak a single data dialect—which is critical for compliance reviews and long-term valuation work.

## Proof Points For Stakeholders

- **Deterministic data lineage** – Every market travels through an audited pipeline: upstream fetch → repository upsert → cache tagging → API exposure. The cycle produces traceable logs and metrics so diligence teams can replay any event.
- **Heartbeat-driven reliability** – Workers advertise liveness via Redis keys with TTLs. If a heartbeat is missed, alerting fires before stale data reaches investor dashboards.
- **Smart economics tracking** – API responses expose rake basis points, settlement hashes, and on-chain identifiers. This enables LPs to model expected yield and for treasury to forecast protocol revenue.
- **Security-first delivery** – Migrations run automatically, containers execute as non-root users, and optional auto-creation of on-chain markets is gated behind explicit configuration plus secure key storage.
- **Perimeter controls baked in** – Trusted-host filters, configurable CORS allowlists, and CSP/HSTS/COOP headers ship with the API. Docker health checks call native Python probes rather than brittle shell scripts.

## Upcoming Enhancements

The roadmap prioritizes capabilities that increase investor trust:

1. **Resolution persistence** – Hydrate on-chain payout vectors into the database so `/resolution` responses remain fast and auditable, even during RPC turbulence.
2. **Schema safety for worker-first deployments** – Allow the worker to enforce Alembic head state, preventing schema drift when API nodes are temporarily offline.
3. **Polymarket resilience** – Shared retry logic and metrics across both services, giving institutional partners real SLAs on data freshness.
4. **Horizen ZEN testnet option** – Spin up a regulated sandbox for exchanges to trial the stack with real capital on a whitelisted network.
5. **Secrets hardening** – Vault-backed signer abstraction so custody providers never handle plaintext keys.

These milestones ladder up to the same thesis: reliable data fuels confident liquidity.

## Service-Level Docs

- [`backend/api/README.md`](./api/README.md) – FastAPI runtime, security headers, health check details, and env vars.
- [`backend/worker/README.md`](./worker/README.md) – Polymarket ingest, cache invalidation, on-chain automation, and worker config.

## Partner Takeaways

- **Integration optionality** – Exchanges can embed only the API, enterprises can operate both API and worker in their own VPC, or sovereign partners can tap our managed service. The shared codebase ensures consistency across every deployment.
- **Observability built in** – Audit teams receive structured logs (request IDs, cache hit ratios, fetch latency) and Prometheus series capturing every pipeline stage.
- **Token-aligned upside** – Because protocol fees are captured at the API layer and mirrored on-chain, governance decisions about rake, settlement cadence, and new markets create tangible upside for future token holders.

To learn how the backend can power your venue, reach out at hello@revealmarket.xyz or via [X](https://x.com/RevealMarket). We are actively onboarding exchanges, OTC desks, and liquidity programs who want transparent exposure to the next generation of prediction markets.

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

## Logging Consistency

Each service now bootstraps a production-grade logger at process start. The format matches `timestamp | LEVEL | logger | file:line | event | message | request_id=<value>` so API, worker, and scripts emit comparable lines. Control verbosity with `LOG_LEVEL`, and opt into rotating files by setting `LOG_TO_FILE=true` (optional knobs: `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`). All logs still stream to stdout for container aggregation, ensuring Docker/Kubernetes collectors see exactly the same structure across services.
