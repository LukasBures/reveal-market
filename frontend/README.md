# Reveal Market Frontend

This directory hosts the marketing + investor documentation experience for Reveal Market. It is a Next.js 15 App Router project that mirrors the polish of a modern crypto venue: glassmorphism surfaces, responsive typography, rich SEO metadata, and parity with the backend’s security posture.

---

## Table of Contents

1. [Stack & Directory Map](#stack--directory-map)
2. [Environment Variables](#environment-variables)
3. [Getting Started](#getting-started)
4. [Mock Data & Offline Workflow](#mock-data--offline-workflow)
5. [Data Fetching & Caching](#data-fetching--caching)
6. [Styling & Design System](#styling--design-system)
7. [Responsive UX Guidelines](#responsive-ux-guidelines)
8. [Testing & Quality Gates](#testing--quality-gates)
9. [Performance & Speed Playbook](#performance--speed-playbook)
10. [Logging & Docker Observability](#logging--docker-observability)
11. [Deployment Checklist](#deployment-checklist)
12. [Troubleshooting](#troubleshooting)

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
| `NEXT_PUBLIC_API_BASE_URL` | Base URL for hitting the FastAPI backend. |
| `NEXT_PUBLIC_API_MOCK` / `RM_API_MOCK` | When `true`, `lib/api.ts` returns seeded mock markets/stats for offline builds/tests. |

When deploying, ensure these values align with the CDN or reverse proxy domain so CSP/HSTS headers reference the correct origin.

---

## Getting Started

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

---

## Mock Data & Offline Workflow

During SSG, the app fetches featured markets, stats, and health snapshots. To avoid backend dependencies:

```bash
export NEXT_PUBLIC_API_MOCK=true    # or RM_API_MOCK=true
npm run build
```

With the mock flag set, `lib/api.ts`:

- Returns seeded `MarketSummary`/`MarketDetail` objects (see `MOCK_MARKETS`).
- Provides deterministic stats + health snapshots.
- Keeps caching logic intact so components behave exactly as they would against the live API.

`frontend/run_tests.sh` enables the mock env vars automatically, so CI/local test runs are hermetic.

Unset the flag (or set to `false`) whenever you need real data.

---

## Data Fetching & Caching

`lib/api.ts` centralizes all network access:

- `fetchFeaturedMarkets(limit, { category, searchQuery, offset })` – Hits `/markets` or `/categories/[slug]` and respects App Router cache tags (`markets:list`, `category:<slug>`). The homepage and category pages rely on this for SSG.
- `useFeaturedMarkets({ limit, searchQuery, category, initialData })` – React Query hook that provides stale-while-revalidate behavior to `FeaturedMarketsClient` so search/category views update gently after hydration.
- `fetchMarketByEventId(eventId)` – Loads detail data and merges backend-provided metadata with Gamma-derived extras (`clob_pair_id`, `resolution_source`, etc.).
- `fetchMarketStatsBreakdown()` / `fetchHealthSnapshot()` – Used for KPI cards, doc callouts, and investor narratives.
- `fetchProofReceipts(limit, { offset })` – Backed by the `/proofs` API and used by `/proofs`’ infinite scroll client to keep the page lightweight.

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

When in doubt, wrap new sections in `glass-panel` to inherit the global blur/gradient aesthetic.

---

## Responsive UX Guidelines

All major pages were tuned for mobile-first:

- Navigation collapses into a “Menu” pill on phones (`MainNav`).
- Hero + KPI sections center text and shrink paddings under `sm:` breakpoints.
- `MarketGrid` switches to `xl:grid-cols-4` on desktops but stays two-up on tablets.
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
  - `home-page.test.tsx` – Ensures hero + featured section render with mocked data.
  - `category-page.test.tsx` – Validates slug parsing and data fetch logic.
  - `market-detail-metadata.test.tsx` – Confirms metadata panel hydration + clipboard actions.
- **Linting**: `npm run lint` follows the Next.js recommended config plus project-specific rules.
- **Preferred workflow**:
  1. `npm run lint`
  2. `npm run test`
  3. Manually inspect `/`, `/categories/politics`, `/markets/<eventId>` in responsive mode.

CI runs these scripts automatically via the repo’s GitHub Actions workflow.

---

## Performance & Speed Playbook

- **Critical-path bundle** – Large client panels (`DocsNav`, `MarketDetailMetadata`, `MarketDetailSidebar`, `/proofs`) ship via `next/dynamic` with lightweight skeletons so Core Web Vitals stay healthy even on mobile connections.
- **Data freshness without jank** – `useFeaturedMarkets` (React Query) hydrates the featured grid with server data, then silently reconciles when `/markets` fetches a fresher batch. Category pages piggyback on the same hook, and proofs rely on offset-based pagination to avoid overfetching.
- **Image & grid density** – Market cards now use a 16:9 art ratio plus responsive `grid-cols-4/5` so more markets fit above the fold on desktop without sacrificing tap targets on mobile.
- **Preconnect hints** – `app/layout.tsx` emits `<link rel="preconnect">` tags for Google Fonts + the configured API origin, shaving DNS + TLS round trips.
- **Mock-friendly builds** – `frontend/run_tests.sh` forces the mock dataset, so `next build` and Vitest never stall on a missing backend. Set `NEXT_PUBLIC_API_MOCK=false` when you want to profile against real endpoints.
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
| `Unable to reach backend` during build | Set `NEXT_PUBLIC_API_MOCK=true`, or ensure the FastAPI service is reachable from your environment. |
| CSP violations in dev | Update `next.config.mjs` to include any new external domains (fonts, analytics, etc.). |
| Scroll layouts jitter on mobile | Confirm `body` retains `scrollbar-gutter` and that new sections don’t override `overflow`. |
| Jest/Vitest can’t parse component | Remember to mark hooks/components that need browser APIs with `"use client"`. |
| Market cards overflow on xl screens | Ensure new props still pass through `MarketGrid` so it can balance columns. |

Need more details? Ping `hello@revealmarket.xyz` or open an issue referencing this README so we can keep the documentation current.
