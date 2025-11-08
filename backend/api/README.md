# Reveal Market API Service

The API exposes every investor-facing surface for Reveal Market: curated market feeds, settlement archives, partner stats, and automation hooks. It is a FastAPI application with hardened security headers, CORS controls, and Redis-backed caching.

## Highlights

- **Security-first defaults** – Trusted-host middleware, configurable CORS allowlists, and CSP/HSTS/COOP headers ship out of the box.
- **Structured logging** – `logging_config.setup_logging()` produces `timestamp | LEVEL | logger | file:line | event | request_id` lines with optional rotating files.
- **Automatic migrations & health checks** – Alembic migrations run on startup, and Docker health checks call `python -m app.healthcheck` to verify Postgres + Redis before serving traffic.
- **Observability** – Prometheus metrics via `prometheus-fastapi-instrumentator`, request IDs in every log, and cache hit/miss events for Redis.

## Running Locally

```bash
cd backend/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
poetry export --help  # optional if you prefer Poetry directly

# Start the API (requires Postgres + Redis running via `run_local.sh` or docker compose)
MODE=dev LOG_LEVEL=DEBUG python run.py
```

Environment variables are prefixed `RM_`. Common ones:

| Variable | Purpose |
| --- | --- |
| `RM_DATABASE_URL` | SQLAlchemy DSN for Postgres. |
| `RM_REDIS_URL` | Redis URI used by caching layer. |
| `RM_ALLOWED_HOSTS` | CSV of hosts for TrustedHost middleware (default `*`). |
| `RM_CORS_ALLOW_ORIGINS` | CSV allowlist for CORS. |
| `RM_ENABLE_SECURITY_HEADERS` | Toggle CSP/HSTS middleware (default `true`). |

## Testing

```bash
cd backend
./run_tests.sh   # runs API + worker pytest suites
```

Pytest uses SQLite/Redis substitutes; no external services required.

## Observability Cheat Sheet

- **Metrics**: `GET /metrics`
- **Health**: `python -m app.healthcheck` (used by Docker) or HTTP `GET /health`
- **Logs**: emitted in JSON-like format with request IDs; set `LOG_TO_FILE=true` to enable rotating files under `/logs`.

## Deployment Notes

- Use the provided Dockerfile (`docker/api/Dockerfile`) for slim runtime layers (Poetry build stage → pip install → non-root user).
- Supply TLS via your ingress; the API enforces HSTS and CSP internally once behind HTTPS.
- Configure `RM_POLYMARKET_*` variables if you need to point at alternative upstream data feeds.
