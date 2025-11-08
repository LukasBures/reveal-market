# Reveal Market Platform

Reveal Market delivers a zero-knowledge prediction stack that regulated venues can actually ship: a FastAPI surface with security hardening, an ingestion/automation worker, investor-grade Next.js experiences, and Groth16-ready Foundry contracts. This mono-repo houses every layer so due diligence, security reviews, and automation live in one place.

Follow progress on X: [@RevealMarket](https://x.com/RevealMarket).

---

## Repository Map

| Directory | Purpose | Highlights |
| --- | --- | --- |
| `backend/api` | FastAPI service for markets, settlements, and partner endpoints. | Trusted-host & CORS controls, CSP/HSTS middleware, Redis caching, pytest suite, docker health probe. |
| `backend/worker` | Async ingestion + optional on-chain automation. | Alembic migrations at boot, structured logging, Polymarket + on-chain sync, pytest suite. |
| `frontend/` | Investor-facing Next.js property. | SEO metadata helpers, CSP headers, sitemap/robots, Vitest coverage, marketing-ready components. |
| `contracts/` | Foundry workspace (RevealMarket, MarketFactory, etc.). | zk-ready settlement events, Forge tests/fuzzing, run scripts, roadmap for Groth16 verifier. |

Additional docs live in each directory’s README.

---

## Investment Snapshot

- **Outcome markets as yield** – Treasury-first rake capture and institutional fee-sharing make markets balance-sheet friendly instead of speculative emissions.
- **Horizen-first + zk moat** – Reveal is the only team operating commit/reveal + Groth16 infrastructure on Horizen’s EVM, giving partners a head start before large CEX integrations land.
- **Compliance-grade delivery** – Segregated services, JSON logging, Prometheus metrics, and security headers keep regulators and auditors aligned from day one.

### Traction

- Multi-service Docker stack ships with health checks, migrations, and hardened logging.
- Investor docs (Next.js) expose sitemap/robots, JSON-LD markup, and legal pages for SEO + AI crawlers.
- Contracts emit `MarketResolved` telemetry today; Foundry tests cover 70+ cases including fuzz/security.

---

## Security & Observability

- **API/Worker** – Strict HSTS, CSP, COOP/CORP, Referrer-Policy, and Trusted Host filters are enabled by default. Health checks are native Python scripts, not cURL hacks.
- **Frontend** – Production headers mirror backend policies; sitemap + robots automatically enumerate investor pages. All docs/legal pages declare canonical URLs and metadata via `lib/seo.ts`.
- **Logging** – Unified formatter across services (`timestamp | LEVEL | logger | file:line | event | request_id`). Optional rotating file output for regulated deployments, structured JSON-LD for site-wide schema.
- **Tests** – `./backend/run_tests.sh` (pytest), `cd frontend && npm run test` (Vitest), `cd contracts && forge test`. CI (`.github/workflows/ci.yml`) runs all three jobs in parallel.

---

## Quick Start

```bash
# Clone & bootstrap
git clone https://github.com/RevealMarket/reveal-market.git
cd reveal-market

# Backend (Python 3.13)
python -m venv backend/api/.venv && source backend/api/.venv/bin/activate
pip install -r backend/api/requirements-dev.txt
deactivate
python -m venv backend/worker/.venv && source backend/worker/.venv/bin/activate
pip install -r backend/worker/requirements-dev.txt
./backend/run_tests.sh

# Frontend
cd frontend && npm install && npm run dev

# Contracts
cd contracts && forge test

# Full docker stack (API, worker, frontend, Postgres, Redis)
./run_local.sh
```

Environment variables follow the `RM_` prefix (see each service README). Security headers can be tuned with `RM_ALLOWED_HOSTS`, CORS lists, and CSP overrides.

---

## Engagement Paths

- **Exchanges & Brokerages** – Deploy the API-only slice behind your firewall, feed liquidity via our worker, or white-label the Next.js storefront.
- **Liquidity Providers & DAOs** – Tap fee-sharing programs, structured webhooks, and rake analytics to model outcome-market exposure.
- **Strategic Investors** – Access diligence packets (contracts, backend, frontend), roadmap briefs, and treasury participation details via `hello@revealmarket.xyz`.

Let’s build prediction markets institutions actually trust.
