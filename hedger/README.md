# Hedger

FastAPI service for exposure tracking and treasury snapshots.

**Entrypoint**
- `hedger/app/main.py`

**Responsibilities**
- Health and metrics endpoints.
- Admin routes for hedger operations.
- Internal data access for treasury and settlement snapshots.

**Hedging Model (v1 Only)**

- Goal: mirror user direction on Polymarket to cover user payouts while the platform keeps its fee.
- If a user takes **YES**, the hedger buys **YES**. If a user takes **NO**, the hedger buys **NO**.
- The platform’s primary exposure is **FX (ZEN/USD)**, not outcome risk.
- Funding: hot USDC.e wallet on Polygon (EOA) with Polymarket CLOB L2 auth.
- Flow: validate USDC.e balance → ensure allowance → submit FAK CLOB order → accept commit only if hedge succeeds.

**Config**
- `hedger/app/config.py`.
  - `HEDGER_ADMIN_READ_ONLY=true` to freeze writes during incidents.
  - `HEDGER_ADMIN_RATE_LIMIT_REQUESTS` / `HEDGER_ADMIN_RATE_LIMIT_WINDOW_SECONDS` for admin throttling.
  - `HEDGER_ADMIN_INTERNAL_SECRET` to require `X-Internal-Secret` for `/admin/commits`.
  - `HEDGER_RISK_CATEGORY_LIMITS` for category exposure limits (JSON map, e.g. `{"crypto":50000}`).
  - CLOB + wallet:
    - `HEDGER_POLYGON_RPC_URL` (default `https://polygon-rpc.com`)
    - `HEDGER_HEDGER_PRIVATE_KEY` (EOA, required)
    - `HEDGER_USDC_ADDRESS` (USDC.e default)
    - `HEDGER_POLYMARKET_EXCHANGE` (spender)
    - `HEDGER_POLYMARKET_CLOB_BASE` (default `https://clob.polymarket.com`)
    - `HEDGER_POLYMARKET_API_KEY` / `HEDGER_POLYMARKET_API_SECRET` / `HEDGER_POLYMARKET_API_PASSPHRASE`
    - `HEDGER_MAX_SLIPPAGE_BPS` / `HEDGER_MIN_FILL_PERCENT`

**Tests**
- `hedger/run_tests.sh`
