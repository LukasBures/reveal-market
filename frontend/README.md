# Reveal Market Frontend

Next.js 15 App Router site for marketing, docs, market discovery, trading, proofs, and the wallet/escrow dashboard. It consumes the FastAPI backend for data and the streamer for live prices/FX. Tailwind powers styling; Vitest + Testing Library cover key UX flows.

```
Browser -> Next.js (SSR + RSC) -> FastAPI backend
                          \--> Streamer (WS/SSE for prices + FX)
                          \--> Relayer/chain (claims, escrow)
```

## Architecture

- **App Router**: `app/layout.tsx` sets global providers (React Query, Wagmi, analytics), nav, and metadata. Routes include `/` (featured markets), `/search`, `/markets/[eventId]`, `/dashboard`, `/proofs`, `/docs/*`, `/contact`, and API proxies under `app/api/*` (suggestions, contact).
- **Data layer**: `lib/api.ts` centralizes backend calls with cache tags that mirror worker invalidation; server actions in `app/actions/` reuse these fetchers for pagination and load-more UX. `lib/seo.ts` holds canonical metadata used by docs/legal pages.
- **Streaming hooks**: `usePriceStream`/`useLiveOutcomePrices` connect to `/stream` WS/SSE with history seeding and HTTP fallback; `useFxStream` keeps a single FX WS alive with stale guards and HTTP fallback.
- **Trading flow**: Stake panel enforces the fixed ticket size (0.1 ZEN by default) plus backend caps, pulls `/pricing/preview` + `/pricing/quote`, submits `/trade/commit`, and polls `/trade/status`. Dashboard uses `/positions`, which now includes `market_summary` (title/outcomes/prices) so it can render positions without extra per-market calls. Deposits/withdrawals are on-chain escrow actions and are not initiated by the API.
- **Security/SEO**: `next.config.mjs` sets CSP/HSTS/COOP/Permissions-Policy and strict image/script origins; sitemap/robots generated from App Router metadata. GA origins only allowed in production.

## Environment

Presets derive from `RM_ENVIRONMENT` (`local` → localhost:3000/8000/8100, `prod` → revealmarket.xyz/api/stream). Override only when deviating; when running in Docker, `STREAMER_PUBLIC_BASE_URL` and `STREAMER_INTERNAL_URL` are also honored.

Common vars:

- `RM_ENVIRONMENT` – preset switch.
- `RM_API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` – backend base URLs (SSR + client).
- `NEXT_PUBLIC_PRICE_STREAMER_URL` / `STREAMER_INTERNAL_URL` (Docker-only) – streamer base for WS/SSE.
- `NEXT_PUBLIC_SITE_URL` / `RM_SITE_URL` – canonical site URL for metadata and sitemap.
- `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` – required for Connect Wallet modal.
- `NEXT_PUBLIC_CHAIN_ID`, `NEXT_PUBLIC_RPC_URL`, `NEXT_PUBLIC_BLOCK_EXPLORER_URL` – target chain (defaults to Horizen Testnet 2651420).
- `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS`, `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS` – collateral + escrow addresses for dashboard.
- Optional toggles: `LANDING_ACCESS_CODE`, `NEXT_PUBLIC_DISABLE_STREAMER_WS`, `NEXT_PUBLIC_DISABLE_PRICE_STREAMS`, `NEXT_PUBLIC_LOG_LEVEL`, `NEXT_PUBLIC_GA_MEASUREMENT_ID`.

## Local Development

> Prereq: Node 20 (see repo `.nvmrc`). Start backend + streamer (e.g., `./run_local.sh`) or point envs at staging.

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000

npm run lint       # ESLint
npm run test       # Vitest + Testing Library
npm run build && npm run start   # production build (used in Docker/CI)
```

`frontend/run_tests.sh` runs lint → test → build; set `FRONTEND_REQUIRE_API=true` to enforce backend health during builds.

## File Map

- `app/` – routes + API proxies + server actions; `app/api/markets/suggest` proxies search suggestions to backend.
- `components/` – nav/footer, hero modules, market cards/grids, trade panels, dashboards, proofs, docs UI.
- `hooks/` – streaming + FX hooks and related utilities.
- `lib/` – API clients, env presets, logging helpers, market mappers, Wagmi config, SEO helpers.
- `tests/` – Vitest suites for navs, hero CTA, docs nav, streaming hooks, market cards, dashboards, proofs.
- `next.config.mjs` – security headers + bundle tweaks.
- `app/globals.css` – global styles + glassmorphism helpers.

## UX Notes

- Market streams prefer WS; pass `assets_ids` (`clobTokenIds`) from the market detail API when opening `/stream`/`/stream/ws` for fastest hydration. Hooks fall back to SSE/HTTP when WS is blocked/stale.
- FX hook marks stale quotes and the UI blocks trading when FX is unavailable; `/pricing/quote` already ignores client FX.
- Claims/escrow flows assume the relayer escrow address and chain id match backend/relayer envs; mismatches prompt chain switch via Wagmi.

## Troubleshooting

- **Blank markets**: verify backend `/healthz` and that Redis is reachable; set `RM_API_BASE_URL` to a live backend.
- **Streams not updating**: check `NEXT_PUBLIC_PRICE_STREAMER_URL` and browser console for CORS/WS errors; set `NEXT_PUBLIC_DISABLE_STREAMER_WS=true` to force SSE/HTTP fallback.
- **Wallet connect fails**: ensure `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` and chain IDs match backend pricing chain.
