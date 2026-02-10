# Hedger

FastAPI service for exposure tracking and treasury snapshots.

**Entrypoint**
- `hedger/app/main.py`

**Responsibilities**
- Health and metrics endpoints.
- Admin routes for hedger operations.
- Internal data access for treasury and settlement snapshots.

**Config**
- `hedger/app/config.py`.
  - `HEDGER_ADMIN_READ_ONLY=true` to freeze writes during incidents.
  - `HEDGER_ADMIN_RATE_LIMIT_REQUESTS` / `HEDGER_ADMIN_RATE_LIMIT_WINDOW_SECONDS` for admin throttling.
  - `HEDGER_RISK_CATEGORY_LIMITS` for category exposure limits (JSON map, e.g. `{"crypto":50000}`).

**Tests**
- `hedger/run_tests.sh`
