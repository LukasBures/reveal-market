# Reveal Market Frontend

This directory hosts the marketing + investor documentation experience for Reveal Market. It is a Next.js 15 App Router project that mirrors the polish of a modern crypto venue: glassmorphism surfaces, responsive typography, rich SEO metadata, and parity with the backend’s security posture.

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
| `app/` | App Router entrypoints. Key routes: `/` (hero + featured markets), `/categories/[category]`, `/markets/[eventId]`, `/docs/*`. |
| `components/` | Shared UI: navigation, footers, market cards/grids, metadata panels, skeleton states, etc. |
| `lib/` | Client helpers (`lib/api.ts`, `lib/seo.ts`, slug parsing utilities). |
| `public/` | Static assets (icons, favicons, OpenGraph image pipeline). |
| `next.config.mjs` | Security headers (CSP, HSTS, COOP/CORP, Referrer-Policy, Permissions-Policy) + bundle tweaks. |

Tech stack callouts:

- **Next.js 15 App Router** with React Server Components, Suspense, and `next/image` where applicable.
- **Tailwind (utility-first)** layered with custom glassmorphism helpers defined in `app/globals.css`.
- **Vitest + Testing Library** for behavioral tests.
- **ESLint + Typescript** enforced via `npm run lint`.

---

## Environment Variables

Set these in `.env.local` (copy from `.env.example`):

| Variable | Purpose |
| -------- | ------- |
| `NEXT_PUBLIC_SITE_URL` | Canonical URL for SEO helpers, JSON-LD schema, sitemap entries. |
| `NEXT_PUBLIC_API_BASE_URL` | Base URL the browser should use (e.g., `http://localhost:8000` when running Docker locally). |
| `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` | WalletConnect Cloud project ID. Required for the Connect Wallet modal + QR code flows. |
| `NEXT_PUBLIC_WALLET_CHAINS` | Optional comma-delimited list of supported chain presets (`base`). Defaults to Base only. |
| `RM_API_BASE_URL` | Internal base URL for server-side fetches. Defaults to `http://api:8000` inside Docker networks. |
| `SITEMAP_API_BASE_URL` | Optional override for sitemap’s market fetches. Point this at an internal API host (e.g., `http://api:8000`) so the backend stays private. |
| `LANDING_ACCESS_CODE` | Optional gatekeeper code for the marketing landing page. When omitted, the gate is disabled. |

When deploying, ensure these values align with the CDN or reverse proxy domain so CSP/HSTS headers reference the correct origin.

---

## Getting Started

> **Prereqs**: Node.js 20 LTS (the repo root `.nvmrc` pins this). Use `nvm use` or your preferred version manager before installing dependencies so Next.js 15.4.7, wagmi 2.x, and the WalletConnect stack all share the same runtime assumptions.

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

Useful scripts:

- `npm run lint` – ESLint (includes Next.js rules + custom config).
- `npm run test` – Vitest test suite.
- `npm run build && npm run start` – production build (used in Docker/CI).

Tip: The repo root `Makefile` surfaces higher-level commands (`make frontend`, etc.) if you prefer a single entry point.

### Wallet connections

`Connect Wallet` in the main nav is powered by Wagmi + WalletConnect v2. Configure `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` and (optionally) `NEXT_PUBLIC_WALLET_CHAINS` before running `npm run dev` so the modal can issue QR codes + deep links. Base is the default (and only) supported chain preset. The modal automatically hides wallets that are not available on the current device (MetaMask only renders when a browser extension/mobile browser is detected, Coinbase Wallet hides on unsupported mobile browsers, WalletConnect stays available everywhere via QR/deep links).

---

## Data Fetching & Caching

`lib/api.ts` centralizes all network access. Every call hits the live FastAPI backend (no mock toggles remain in production):

- `fetchFeaturedMarkets(limit, { category, searchQuery, offset })` – Hits `/markets` or `/categories/[slug]` and respects App Router cache tags (`markets:list`, `category:<slug>`). The homepage and category pages rely on this for SSG.
- `loadFeaturedMarketsAction(limit, options)` – A server action used by `FeaturedMarketsClient` and other client entry points so “Load more” reuses the same fetcher/cache tags that SSR used.
- `useFeaturedMarkets({ limit, searchQuery, category, initialData })` – React Query hook that wraps the server action and provides stale-while-revalidate behavior to client components.
- `fetchMarketByEventId(eventId)` – Loads detail data and merges backend-provided metadata with Gamma-derived extras (`clob_pair_id`, `resolution_source`, etc.).
- `fetchMarketStatsBreakdown()` / `fetchHealthSnapshot()` – Used for KPI cards, doc callouts, and investor narratives.
- `fetchProofReceipts(limit, { offset })` – Backed by the `/proofs` API and used by `/proofs`’ infinite scroll client to keep the page lightweight.
- `fetchMarketSuggestions(query, limit)` – Powers `/app/api/markets/suggest` so the global search dropdown hits a cached Next.js route instead of calling the backend twice per keystroke.

Every fetch call sets `cache` + `next.revalidate` hints so hydration stays fast while still respecting backend invalidation tags that the worker publishes.

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
- **Typography** – Manrope is loaded via `next/font/google`. When adding new copy, keep headings within `text-3xl`–`text-4xl` and supporting paragraphs at `text-base` or `text-sm` for readability on mobile.
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
  4. For CI parity run `./frontend/run_tests.sh`, which verifies the API at `NEXT_PUBLIC_API_BASE_URL` is reachable before linting/building.

CI runs these scripts automatically via the repo’s GitHub Actions workflow.

---

## Performance & Speed Playbook

- **Critical-path bundle** – Large client panels (`DocsNav`, `MarketDetailMetadata`, `MarketDetailSidebar`, `/proofs`) ship via `next/dynamic` with lightweight skeletons so Core Web Vitals stay healthy even on mobile connections.
- **Data freshness without jank** – `useFeaturedMarkets` (React Query) hydrates the featured grid with server data, then silently reconciles when `/markets` fetches a fresher batch. Category pages piggyback on the same hook, and proofs rely on offset-based pagination to avoid overfetching.
- **Image & grid density** – Market cards show a compact square thumbnail beside metadata, and `MarketGrid` caps at three columns on desktop so the layout matches the marketing requirements while still collapsing to one/two columns on smaller screens.
- **Preconnect hints** – `app/layout.tsx` emits `<link rel="preconnect">` tags for Google Fonts + the configured API origin, shaving DNS + TLS round trips.
- **Backend-ready builds** – `frontend/run_tests.sh` now refuses to run unless the Dockerized API is reachable at `NEXT_PUBLIC_API_BASE_URL`. Keep `docker compose up` running locally (or point the env var at a staging host) before invoking the script.
- **Speed validation** – After visual QA, run `npm run lint && npm run test && npm run build`, then Lighthouse/Chrome traces focusing on LCP (<1.2s), CLS (<0.02), and smooth main-thread (<50ms/interaction).

---

## Logging & Docker Observability

- `frontend/lib/logging.ts` exposes structured `logger` helpers. Logs default to INFO, include JSON metadata, and the Docker console gets a heartbeat message (`"I am still here"`) every `HEARTBEAT_INTERVAL_MS` milliseconds (defaults to 60s; override with `NEXT_PUBLIC_HEARTBEAT_INTERVAL_MS` or `HEARTBEAT_INTERVAL_MS`).
- Every fetch helper logs success/error states (`fetchFeaturedMarkets:success`, `fetchProofReceipts:error`, etc.) so you can correlate frontend issues with backend traces.
- `ensureHeartbeat()` runs in `RootLayout`, so every container (dev server, `next start`, Docker standalone) proves liveness even when traffic is idle.
- When running under Docker, `docker/frontend/Dockerfile` uses a multi-stage build: `npm ci` runs in a deps layer, source is copied from the repo (no host `node_modules` bind mounts), and the final image serves the standalone output as a non-root user.
- For noisy environments, drop `NEXT_PUBLIC_LOG_LEVEL=warn` or tweak the heartbeat interval; for deep debugging set `LOG_LEVEL=debug` to surface client fetch metadata.

---

## Deployment Checklist

1. `npm install && npm run lint && npm run test`.
2. `npm run build` (ensures there are no SSG/ISR surprises).
3. Provide `NEXT_PUBLIC_SITE_URL` + `NEXT_PUBLIC_API_BASE_URL` secrets in your hosting platform.
4. Serve over HTTPS so CSP/HSTS headers take effect. If you terminate TLS upstream (Cloudflare, Fastly, etc.), mirror the security headers there.
5. Configure caching:
   - Static assets: long-lived CDN cache.
   - App routes: let Next.js handle incremental cache (the worker invalidates tags automatically).
6. Docker tip: when using `docker/frontend/Dockerfile`, pass `--build-arg NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain` so server-side rendering + JSON-LD reference the proper host.

Docker images rely on `next build` + `next start --turbo` by default; see the repository root for compose examples.

---

## Troubleshooting

| Symptom | Fix |
| ------- | ---- |
| `Unable to reach backend` during build | Start the Docker stack (`docker compose up postgres redis proover api worker`) so the API answers at `NEXT_PUBLIC_API_BASE_URL` before running `npm run build`. |
| CSP violations in dev | Update `next.config.mjs` to include any new external domains (fonts, analytics, etc.). |
| Scroll layouts jitter on mobile | Confirm `body` retains `scrollbar-gutter` and that new sections don’t override `overflow`. |
| Jest/Vitest can’t parse component | Remember to mark hooks/components that need browser APIs with `"use client"`. |
| Market cards overflow on xl screens | Ensure new props still pass through `MarketGrid` so it can balance columns. |

Need more details? Ping `hello@revealmarket.xyz` or open an issue referencing this README so we can keep the documentation current.
