# Reveal Market Frontend

This directory hosts the Reveal Market web experience (marketing, docs, search, trading, proofs, and dashboard). It is a Next.js 15 App Router project that mirrors the polish of a modern crypto venue: glassmorphism surfaces, responsive typography, rich SEO metadata, and security headers aligned with the backend.

---

## Table of Contents

1. [Stack & Directory Map](#stack--directory-map)
2. [Environment Variables](#environment-variables)
3. [Getting Started](#getting-started)
4. [Data Fetching & Caching](#data-fetching--caching)
5. [Styling & Design System](#styling--design-system)
6. [Responsive UX Guidelines](#responsive-ux-guidelines)
7. [Testing & Quality Gates](#testing--quality-gates)
8. [Performance & Speed Playbook](#performance--speed-playbook)
9. [Logging & Docker Observability](#logging--docker-observability)
10. [Deployment Checklist](#deployment-checklist)
11. [Troubleshooting](#troubleshooting)

---

## Stack & Directory Map

| Area | Description |
| ---- | ----------- |
| `app/` | App Router routes + API proxies + server actions. Key routes: `/` (hero + featured markets), `/markets/search`, `/markets/[eventId]`, `/dashboard`, `/proofs`, `/docs/*`, `/contact`. |
| `components/` | Shared UI: navigation, footers, market cards/grids, trade panels, dashboards, proofs, docs. |
| `hooks/` | Streaming + FX hooks (`usePriceStream`, `useFxStream`, `useLiveOutcomePrices`). |
| `lib/` | API clients, env presets, logging, market mappers, wagmi config. |
| `tests/` | Vitest suites + test utilities. |
| `public/` | Static assets (icons, favicons, OpenGraph image pipeline). |
| `next.config.mjs` | Security headers (CSP, HSTS, COOP/CORP, Referrer-Policy, Permissions-Policy) + bundle tweaks. |

Tech stack callouts:

- **Next.js 15 App Router** with React Server Components, Suspense, and `next/image` where applicable.
- **Tailwind (utility-first)** layered with custom glassmorphism helpers defined in `app/globals.css`.
- **Vitest + Testing Library** for behavioral tests; **ESLint + TypeScript** enforced via `npm run lint`.
- **Live pricing UI** – Streams market data from the streamer over WS/SSE (prefers WS, SSE fallback) and uses `clobTokenIds` for `assets_ids` so books/trades hydrate fast; optional toggles can disable streams.
- **Collateral + escrow** – ZEN token + relayer escrow addresses come from `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS` and `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS`; dashboard supports approve/deposit/withdraw and claim flows.
- **Server actions + API proxies** – SSR routes call the FastAPI backend directly, while `app/api/*` proxies pass search/proofs/contact traffic through Next to preserve cookies/headers. `AppProviders` shares a single React Query + Wagmi config across the tree.
- **Streaming + FX resilience** – `usePriceStream`/`useLiveOutcomePrices` multiplex a shared WS stream per market with backoff and history seeding; `useFxStream` keeps one FX WS alive with HTTP fallbacks and stale guards so price cards stay safe when WS is blocked or slow.
- **Signed quotes + relayer commit** – Preview quotes from `/pricing/preview`, signed quotes from `/pricing/quote`, submit via `/trade/commit`, and poll `/trade/status` for tx hash; on-chain claims use `claim` via wagmi/viem.

## What’s Implemented Today

- **SSR-first data** – All routes fetch directly from the FastAPI backend; cache tags mirror worker invalidation so `revalidateTag` and server actions stay aligned. Suggestions proxy through `/app/api/markets/suggest` to avoid double hits.
- **Search + discovery** – Hero suggestions, `/markets/search` with load-more pagination, and category pages reuse the same cached fetchers.
- **Live pricing** – `usePriceStream`/`useLiveOutcomePrices` tie WS/SSE `/stream` to market detail; history hydrates from the streamer and merges live ticks. FX uses WS-first `/fx/zen-usd` with HTTP fallback + stale warnings that block trades.
- **Trading flow** – Stake panels enforce the 0.1 ZEN ticket size + caps, request previews from `/pricing/preview`, fetch signed quotes from `/pricing/quote`, submit `/trade/commit`, and poll `/trade/status` for relayer/tx updates.
- **Positions + escrow** – `/dashboard` shows escrow balances, approve/deposit/withdraw, positions, and per-ticket claims after a bundle signature.
- **Proof receipts** – `/proofs` streams receipts with infinite scroll and supports deep links via query params.
- **Security + observability** – `next.config.mjs` ships CSP/HSTS/COOP/Permissions-Policy; GA/gtag only allowed in production. Structured logs and a client heartbeat run from `RootLayout`, plus Vitest coverage across navs, markets, streaming hooks, dashboards, and proofs.

---

## Environment Variables

Defaults are derived from `RM_ENVIRONMENT` (`local` → localhost:3000/8000/8100, `prod` → revealmarket.xyz/api/stream). You only need to set overrides when deviating from those presets. Common knobs:

| Variable | Purpose |
| -------- | ------- |
| `RM_ENVIRONMENT` | Preset mode (`local` or `prod`) for API/streamer/site defaults. |
| `RM_API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` | Override FastAPI base for SSR + client calls. |
| `NEXT_PUBLIC_PRICE_STREAMER_URL` / `STREAMER_INTERNAL_URL` | Streamer base for WS/SSE; internal URL is used server-side in Docker. |
| `NEXT_PUBLIC_SITE_URL` / `RM_SITE_URL` | Canonical site URL for metadata, sitemap, and SEO. |
| `LANDING_ACCESS_CODE` | Optional gatekeeper code for the marketing landing page. When omitted, the gate is disabled. |
| `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` | WalletConnect Cloud project ID. Required for the Connect Wallet modal + QR code flows. |
| `NEXT_PUBLIC_CHAIN_ID` / `NEXT_PUBLIC_CHAIN_NAME` | Target chain for wagmi/viem (defaults: Horizen Testnet `2651420`, name `"Horizen Testnet"`). |
| `NEXT_PUBLIC_RPC_URL` / `NEXT_PUBLIC_BLOCK_EXPLORER_URL` / `NEXT_PUBLIC_EXPLORER_BASE_URL` | RPC + explorer for the target chain (defaults: `https://horizen-testnet.rpc.caldera.xyz/http`, `https://horizen-testnet.explorer.caldera.xyz`). |
| `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS` / `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS` | ERC20 collateral + escrow addresses (required for dashboard funding + claim UX). |
| `NEXT_PUBLIC_GA_MEASUREMENT_ID` | Google Analytics (empty to disable). |

Optional toggles:

- `NEXT_PUBLIC_DISABLE_STREAMER_WS` / `NEXT_PUBLIC_DISABLE_PRICE_STREAMS` – force SSE fallback or disable streaming entirely.
- `NEXT_PUBLIC_LOG_LEVEL`, `NEXT_PUBLIC_ENABLE_BROWSER_LOGS`, `NEXT_PUBLIC_FRONTEND_LOG_ENDPOINT`, `NEXT_PUBLIC_HEARTBEAT_INTERVAL_MS` – tune logging and heartbeat behavior.

When deploying, ensure these values align with the CDN or reverse proxy domain so CSP/HSTS headers reference the correct origin.

---

## Getting Started

> **Prereqs**: Node.js 20 LTS (the repo root `.nvmrc` pins this). Use `nvm use` or your preferred version manager before installing dependencies so Next.js 15.4.7, wagmi 3.x, and the WalletConnect stack all share the same runtime assumptions.

```bash
cd frontend
npm install
npm run dev        # serves on :3000 (hit https://revealmarket.xyz via your TLS proxy/hosts entry)
```

Ensure the backend + streamer are reachable (e.g., `./run_local.sh`) or point `RM_API_BASE_URL`/`NEXT_PUBLIC_PRICE_STREAMER_URL` at staging so SSR + streaming calls succeed.

Useful scripts:

- `npm run lint` – ESLint (includes Next.js rules + custom config).
- `npm run test` – Vitest test suite.
- `npm run build && npm run start` – production build (used in Docker/CI).
- `cp ../.env.production frontend/.env.production` – if you keep a single prod env at repo root, copy it into `frontend/` before building so Next.js picks it up (keep real secrets out of git; use the example as the template).

Tip: The repo root `Makefile` surfaces higher-level commands (`make frontend`, etc.) if you prefer a single entry point.

> **Tests & backend dependency:** `npm run test` mocks fetch in most suites; `frontend/run_tests.sh` runs lint/test/build. For CI parity, start the backend stack (or point `RM_API_BASE_URL` at staging) and set `FRONTEND_REQUIRE_API=true` to enforce the `/health` check.

### Wallet connections

`Connect Wallet` in the main nav is powered by Wagmi 3 + WalletConnect v2 plus injected/coinbase connectors. The app targets a single chain (defaults to Horizen Testnet `2651420`) and will auto-prompt a switch when a mismatched chain is detected. Set `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` before running `npm run dev` so the QR modal comes online.

---

## Data Fetching & Caching

`lib/api.ts` centralizes all network access. Every call hits the live FastAPI backend (no mock toggles remain in production):

- `fetchFeaturedMarkets(limit, { category, searchQuery, offset })` – Hits `/markets` or `/categories/[slug]` and respects App Router cache tags (`markets:list`, `category:<slug>`). The homepage and category pages rely on this for SSG.
- `loadFeaturedMarketsAction(limit, options)` – A server action used by `FeaturedMarketsClient` and other client entry points so “Load more” reuses the same fetcher/cache tags that SSR used.
- `useFeaturedMarkets({ limit, searchQuery, category, initialData })` – React Query hook that wraps the server action and provides stale-while-revalidate behavior to client components.
- `fetchMarketByEventId(eventId)` – Loads detail data and merges backend-provided metadata with Gamma-derived extras (`clob_pair_id`, `resolution_source`, etc.).
- `fetchGroupedMarkets(groupSlug)` – Loads grouped market bundles for multi-outcome events and the group selector.
- `fetchMarketStatsBreakdown()` / `fetchHealthSnapshot()` – Used for KPI cards, doc callouts, and investor narratives.
- `fetchProofReceipts(limit, { offset, marketId, eventId, conditionId, requestId })` – Backed by the `/proofs` API and used by `/proofs`’ infinite scroll client to keep the page lightweight.
- `fetchMarketSuggestions(query, limit)` – Powers `/app/api/markets/suggest` so the global search dropdown hits a cached Next.js route instead of calling the backend twice per keystroke.
- `fetchPricingPreview(...)` / `fetchPricingQuoteWithMeta(...)` – Preview quotes for UI plus signed quotes for trades, with caps and expiries baked in.
- `submitTrade(quoteId)` / `fetchTradeStatus(...)` – Sends `/trade/commit` and polls `/trade/status` for relayer updates + tx hash.
- `fetchPositions(wallet)` / `fetchClaimBundles(wallet, signature)` – Powers the `/dashboard` positions table and claim flow.

Every fetch call sets `cache` + `next.revalidate` hints so hydration stays fast while still respecting backend invalidation tags that the worker publishes.

### Trading flow (FX + quotes)
- FX hook prefers WS/WSS (`/fx/zen-usd`, aliased from `/fx/zen-usdc`) with periodic HTTP fallback; after a few fallbacks it re-attempts WS automatically.
- Preview quotes (`/pricing/preview`) keep the UI responsive; signed quotes (`/pricing/quote`) include caps, expiry, and `quote_id`.
- Trades submit to `/trade/commit` (relayer) and poll `/trade/status` for tx hash + confirmations; ensure the connected chain matches the quote’s `chain_id`.
- Stake size is fixed at 0.1 ZEN and capped further by per-user/per-market limits; stale FX disables trading.

### Lazy loading & pagination

- Heavy client surfaces (`/proofs`, docs navigation, market metadata/sidebars) load via `next/dynamic`, trimming the critical bundle for hero views.
- `/proofs` renders a small seed list on the server and then hands off to `ProofsClient` for infinite scroll pagination (manual button + `IntersectionObserver` auto-load).
- Category pages call `CategoryMarkets` which fans out to `fetchFeaturedMarkets` and gracefully falls back to featured pools if a category stream is empty.
- `AppProviders` (wired up in `app/layout.tsx`) bootstraps a shared `QueryClient` so any client hook can piggyback on caching without repeat providers.

---

## Styling & Design System

- **Globals** – `app/globals.css` defines the dark gradient background, `glass-panel` helper, and subtle animation utilities (`fade-up`, text glow, divider gradients).
- **Components** – Prefer the shared components under `components/markets`:
  - `MarketFilters` (hero/search)
  - `MarketGrid` + `MarketCard` (supports 2/3/4 column layouts automatically)
  - `MarketDetailHeader/Metadata/Sidebar/Outcomes`
- **Spacing** – Use the existing Tailwind spacing scale (`px-4 py-6`, `rounded-3xl`, etc.) to maintain visual rhythm.
- **Typography** – Manrope is loaded via `next/font/google`; Autobus Bold is a local display face (use `font-display` when needed). When adding new copy, keep headings within `text-3xl`–`text-4xl` and supporting paragraphs at `text-base` or `text-sm` for readability on mobile.
- **Brand assets** – Source logos, gradients, and lockups are stored in [this shared Drive folder](https://drive.google.com/drive/u/0/folders/1tHh_4g5wugT2LusltcLbopsyyH1MupQd); reference it before exporting new files into `public/brand` or the mockups directory.

When in doubt, wrap new sections in `glass-panel` to inherit the global blur/gradient aesthetic.

---

## Responsive UX Guidelines

All major pages were tuned for mobile-first:

- Navigation collapses into a “Menu” pill on phones (`MainNav`).
- Hero + KPI sections center text and shrink paddings under `sm:` breakpoints.
- `MarketGrid` caps at three columns on desktops (`xl:grid-cols-3`) and stays two-up on tablets.
- Tables (e.g., `MarketDetailOutcomes`) sit inside `overflow-x-auto` containers so they’re usable on narrow screens.

If you introduce new components, test at these breakpoints:

| Breakpoint | Width | Expectations |
| ---------- | ----- | ------------ |
| base (`<640px`) | Phone | Centered copy, full-width CTAs, tap-friendly buttons. |
| `sm` (≥640px) | Small tablets | Begin left-aligning text, maintain 2-column grids. |
| `lg` (≥1024px) | Desktop | Reveal 3–4 column grids, align hero copy with the search module. |
| `xl` (≥1280px) | Large desktop | Extra breathing room for cards; avoid >1200px text widths. |

---

## Testing & Quality Gates

- **Unit/UI tests**: `npm run test`. Key suites:
  - `market-filters.test.tsx` – Search input, router interactions, suggestion fallback.
  - `home-page.test.tsx` – Ensures hero + featured sections render with deterministic fixtures.
  - `category-page.test.tsx` – Validates slug parsing and data fetch logic.
  - `market-detail-metadata.test.tsx` – Confirms metadata panel hydration + clipboard actions.
- **Linting**: `npm run lint` follows the Next.js recommended config plus project-specific rules.
- **Preferred workflow**:
  1. `npm run lint`
  2. `npm run test`
  3. Manually inspect `/`, `/categories/politics`, `/markets/<eventId>` in responsive mode.
  4. For CI parity run `./frontend/run_tests.sh` with the backend reachable; set `FRONTEND_REQUIRE_API=true` to enforce the `/health` check.

CI runs these scripts automatically via the repo’s GitHub Actions workflow.

---

## Performance & Speed Playbook

- **Critical-path bundle** – Large client panels (`DocsNav`, `MarketDetailMetadata`, `MarketDetailSidebar`, `/proofs`) ship via `next/dynamic` with lightweight skeletons so Core Web Vitals stay healthy even on mobile connections.
- **Data freshness without jank** – `useFeaturedMarkets` (React Query) hydrates the featured grid with server data, then silently reconciles when `/markets` fetches a fresher batch. Category pages piggyback on the same hook, and proofs rely on offset-based pagination to avoid overfetching.
- **Image & grid density** – Market cards show a compact square thumbnail beside metadata, and `MarketGrid` caps at three columns on desktop so the layout matches the marketing requirements while still collapsing to one/two columns on smaller screens.
- **Preconnect hints** – `app/layout.tsx` emits `<link rel="preconnect">` tags for Google Fonts + the configured API origin, shaving DNS + TLS round trips.
- **Backend-aware builds** – SSR fetches hit the API; for CI/MVP runs keep the backend reachable (or point `RM_API_BASE_URL` at staging). Use `FRONTEND_REQUIRE_API=true` to enforce a `/health` check locally.
- **Speed validation** – After visual QA, run `npm run lint && npm run test && npm run build`, then Lighthouse/Chrome traces focusing on LCP (<1.2s), CLS (<0.02), and smooth main-thread (<50ms/interaction).

## Streaming & FX

- **FX source** – Frontend consumes the streamer FX websocket at `/fx/zen-usd` (worsen% applied). Hook: `useFxStream(path)` handles WS with backoff, HTTP fallback, and stale/error states; used by `MainNav` and `StakeQuoteCard`.
- **Market prices** – Live odds stream from streamer `/stream` (WS preferred, SSE fallback) via `usePriceStream` and `useLiveOutcomePrices`, surfacing `display_price` and `fx_stale` flags on market detail pages.
- **WSS/TLS** – Streamer defaults follow `RM_ENVIRONMENT` (prod → `https://stream.revealmarket.xyz`, local → `http://localhost:8100`) and auto-switch to `wss://` for websockets. Caddy config for TLS termination lives in `docker/caddy/Caddyfile`.
- **Env summary** – Defaults come from `RM_ENVIRONMENT` (prod/local presets). Override with `RM_API_BASE_URL`/`NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_PRICE_STREAMER_URL`/`STREAMER_INTERNAL_URL` only when needed; `NEXT_PUBLIC_DISABLE_STREAMER_WS` and `NEXT_PUBLIC_DISABLE_PRICE_STREAMS` control stream behavior.

## Deployment / Runbook

- **Env vars**: Mostly preset by `RM_ENVIRONMENT`; optional overrides include `RM_API_BASE_URL`/`NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_PRICE_STREAMER_URL`/`STREAMER_INTERNAL_URL`, `NEXT_PUBLIC_SITE_URL`, wallet provider keys, and analytics keys. Ensure `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS` + `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS` are set for escrow/claim flows.
- **TLS**: Terminate at Caddy/Nginx; streamer and API are HTTP internally. Ensure the streamer host is whitelisted in CSP if embedded.
- **Health**: API `/health` (or `/healthz`), streamer `/healthz`; keep the backend reachable for CI/MVP runs and consider `FRONTEND_REQUIRE_API=true` for local checks.
- **Cache warmup**: Optional—preload featured markets via `/markets?limit=20` and FX via `/pricing/fx` to prime CDN/cache layers after deploy.
- **Smoke**: Run `npm run lint && npm run test && npm run build`; for live pricing, confirm `MainNav` shows FX and a market detail page receives live price ticks.

---

## Logging & Docker Observability

- `frontend/lib/logging.ts` exposes structured `logger` helpers. Logs default to INFO, include JSON metadata, and the Docker console gets a heartbeat message (`"I am still here"`) every `HEARTBEAT_INTERVAL_MS` milliseconds (defaults to 60s; override with `NEXT_PUBLIC_HEARTBEAT_INTERVAL_MS` or `HEARTBEAT_INTERVAL_MS`).
- Every fetch helper logs success/error states (`fetchFeaturedMarkets:success`, `fetchProofReceipts:error`, etc.) so you can correlate frontend issues with backend traces.
- `ensureHeartbeat()` runs in `RootLayout`, so every container (dev server, `next start`, Docker standalone) proves liveness even when traffic is idle.
- When running under Docker, `docker/frontend/Dockerfile` uses a multi-stage build: `npm ci` runs in a deps layer, source is copied from the repo (no host `node_modules` bind mounts), and the final image serves the standalone output as a non-root user.
- For noisy environments, drop `NEXT_PUBLIC_LOG_LEVEL=warn` or tweak the heartbeat interval; set `NEXT_PUBLIC_ENABLE_BROWSER_LOGS=true` + `NEXT_PUBLIC_FRONTEND_LOG_ENDPOINT` to ship client logs, and use `LOG_LEVEL=debug` for server-side fetch metadata.

---

## Deployment Checklist

1. `npm install && npm run lint && npm run test`.
2. `npm run build` (ensures there are no SSG/ISR surprises).
3. Ensure `RM_ENVIRONMENT=production` in your hosting platform; override `RM_API_BASE_URL`/`NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_PRICE_STREAMER_URL`/`STREAMER_INTERNAL_URL`, and `NEXT_PUBLIC_SITE_URL` only if pointing at non-standard hosts; set `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS` + `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS` for live trading.
4. Serve over HTTPS so CSP/HSTS headers take effect. If you terminate TLS upstream (Cloudflare, Fastly, etc.), mirror the security headers there.
5. Configure caching:
   - Static assets: long-lived CDN cache.
   - App routes: let Next.js handle incremental cache (the worker invalidates tags automatically).
6. Docker tip: when using `docker/frontend/Dockerfile`, set `RM_ENVIRONMENT=production` so server-side rendering + JSON-LD reference the production presets.

Docker images rely on `next build` + `next start --turbo` by default; see the repository root for compose examples.

---

## Troubleshooting

| Symptom | Fix |
| ------- | ---- |
| `Unable to reach backend` during build | Ensure the API answers `/health` at the configured base or point `RM_API_BASE_URL` at staging; set `FRONTEND_REQUIRE_API=true` if you want `run_tests.sh` to enforce it. |
| WalletConnect QR modal missing | Set `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` and restart the dev server. |
| Trade/escrow buttons disabled | Check for chain mismatch and confirm `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS` + `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS` are set. |
| Streamer/FX blocked on HTTPS | Use HTTPS/WSS streamer URLs or set `NEXT_PUBLIC_DISABLE_STREAMER_WS=true` to force REST/SSE fallback. |
| CSP violations in dev | Update `next.config.mjs` to include any new external domains (fonts, analytics, etc.). |
| Scroll layouts jitter on mobile | Confirm `body` retains `scrollbar-gutter` and that new sections don’t override `overflow`. |
| Jest/Vitest can’t parse component | Remember to mark hooks/components that need browser APIs with `"use client"`. |
| Market cards overflow on xl screens | Ensure new props still pass through `MarketGrid` so it can balance columns. |

Need more details? Open an issue referencing this README or reach out via the `/contact` page so we can keep the documentation current.
