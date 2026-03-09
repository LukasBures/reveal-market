# Frontend

Next.js 15 + TypeScript + Tailwind app for the marketing site and event browsing UI.

## Stack

- **Framework**: Next.js 15 (App Router, `output: standalone`)
- **Language**: TypeScript, Node >=20.0.0 <21.0.0
- **Styling**: Tailwind CSS
- **Web3**: wagmi + viem, WalletConnect, Coinbase Wallet, MetaMask, Rabby, OKX Wallet
- **Chain**: Horizen Testnet (chain ID `2651420`, native currency ZEN)

## Development

```bash
npm run dev          # Next.js dev server (http://localhost:3000)
npm run build        # Production build
npm run generate:css # Regenerate Tailwind CSS
npm run lint         # ESLint
npm run lighthouse:ci
npm run bundle:check
```

## Testing

```bash
npm run test                                           # full test suite (Vitest)
npm run test -- --run tests/components/MarketCard.test.tsx  # single file
```

Tests and builds only enforce backend `/health` when `FRONTEND_REQUIRE_API=true`; otherwise they warn and proceed.

## App Structure

### Public pages — `app/(public)/`

| Route | File |
|-------|------|
| `/` | `(public)/page.tsx` |
| `/[category]` | `(public)/[category]/page.tsx` |
| `/search` | `(public)/search/page.tsx` |
| `/about` | `(public)/about/page.tsx` |
| `/contact` | `(public)/contact/page.tsx` |
| `/docs` | `(public)/docs/page.tsx` |
| `/docs/getting-started` | `(public)/docs/getting-started/page.tsx` |
| `/docs/privacy-security` | `(public)/docs/privacy-security/page.tsx` |
| `/docs/faq` | `(public)/docs/faq/page.tsx` |
| `/terms` | `(public)/terms/page.tsx` |
| `/privacy` | `(public)/privacy/page.tsx` |
| `/legal` | `(public)/legal/page.tsx` |
| `/cookies` | `(public)/cookies/page.tsx` |
| `/disclaimer` | `(public)/disclaimer/page.tsx` |

### App pages — `app/(app)/`

| Route | File |
|-------|------|
| `/dashboard` | `(app)/dashboard/page.tsx` |
| `/events/[eventId]` | `(app)/events/[eventId]/page.tsx` |
| `/proofs` | `(app)/proofs/page.tsx` |

### Next.js API route handlers — `app/api/`

| Route | Method | Description |
|-------|--------|-------------|
| `/api/health` | GET | Health check (proxies backend `/health`) |
| `/api/events/list` | GET | Proxies backend event listing |
| `/api/events/suggest` | GET | Proxies backend event suggestions |
| `/api/markets/list` | GET | Proxies backend market listing |
| `/api/markets/suggest` | GET | Proxies backend market suggestions |
| `/api/proofs` | GET | Proxies backend proof receipts |
| `/api/contact` | POST | Contact form submission |

### Other routes

| Route | File |
|-------|------|
| `/healthz` | `app/healthz/route.ts` |
| `/sitemap.xml` | `app/sitemap.xml/route.ts` |
| `/sitemap-events.xml` | `app/sitemap-events.xml/route.ts` |
| `/sitemap-pages.xml` | `app/sitemap-pages.xml/route.ts` |

## Key `lib/` Modules

| File | Purpose |
|------|---------|
| `api.ts` | All backend fetches (`fetchFeaturedEvents`, `fetchMarketByEventId`, `fetchProofReceipts`, `fetchPositions`, `fetchClaimBundles`, `fetchTradeStatus`, `fetchMarketSuggestions`, `fetchMarketStatsBreakdown`) |
| `api-types.ts` | Shared TypeScript types for API responses |
| `wagmi.ts` | Wallet/Web3 config — chain, connectors, wagmiConfig |
| `seo.ts` | Centralized metadata: `buildMetadata`, `docsMetadata`, JSON-LD helpers |
| `env-presets.ts` | Mode detection (`local`/`prod`) and URL resolution for API, streamer, and site URL |
| `serverEnv.ts` | Server-side env helper that reads from `env-presets.ts` |
| `marketMapper.ts` | Shapes raw API responses into `MarketSummary` |
| `markets.ts` | Sort/filter helpers and `MARKET_CATEGORY_FILTERS` |
| `pricing-client.ts` | Quote/pricing client |
| `streamer-data.ts` | Subgraph fetch helpers (tokens, OI, orderbook aggregates) |
| `formatters.ts` | Number and date formatters |
| `logging.ts` | Structured logger (`timestamp | LEVEL | logger | file:line | event`) |
| `poseidon.ts` | BN254 Poseidon hash implementation (client-side commits) |
| `marketContract.ts` | Typed contract call helpers |
| `signature-messages.ts` | EIP-712 / typed message definitions |
| `redis.ts` | Server-side Redis client (used by API route handlers) |
| `slugs.ts` | URL slug utilities |
| `tokens.ts` | Token address helpers |
| `fx.ts` | FX rate helpers |

### `lib/server/`

Server-only utilities (never imported in client components).

## Wagmi Configuration

Defined in `lib/wagmi.ts`.

**Chain**: Horizen Testnet

| Field | Default | Override |
|-------|---------|----------|
| Chain ID | `2651420` | `NEXT_PUBLIC_CHAIN_ID` |
| Chain name | `Horizen` | `NEXT_PUBLIC_CHAIN_NAME` |
| RPC URL | `https://horizen-testnet.rpc.caldera.xyz/http` | `NEXT_PUBLIC_RPC_URL` |
| Block explorer | `https://horizen-testnet.explorer.caldera.xyz` | `NEXT_PUBLIC_BLOCK_EXPLORER_URL` |
| Native currency | ZEN (18 decimals) | — |

**Connectors**: MetaMask (injected), Rabby (injected), OKX Wallet (injected), generic injected, Coinbase Wallet, WalletConnect (when `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` is set).

WalletConnect is silently disabled when the project ID is not set; a console warning is emitted.

## SEO

Metadata lives in `lib/seo.ts`. Use `buildMetadata(...)` for all pages and `docsMetadata(slug)` for docs pages. All pages should set canonical URLs via `alternates.canonical`.

Docs slugs: `overview`, `getting-started`, `privacy-security`, `faq`.

JSON-LD helpers: `buildBreadcrumbJsonLd`, `buildFaqJsonLd`, `buildArticleJsonLd`, `buildContactPageJsonLd`.

## Security Headers

Set in `next.config.mjs` for all routes via the `headers` async function. Headers include CSP, HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, CORP, and COOP.

CSP `connect-src` includes both local and production API/streamer origins. GA/gtag origins are added to `script-src` and `connect-src` in production only (`isProd`).

When adding new external origins, whitelist them in **both** `next.config.mjs` and `backend/api/app/security.py`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `RM_ENVIRONMENT` | No | Deployment mode: `local` (default) or `prod` |
| `NEXT_PUBLIC_RM_ENVIRONMENT` | No | Client-side mode override (same values) |
| `RM_API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` | No | Backend API base URL override |
| `NEXT_PUBLIC_SITE_URL` / `RM_SITE_URL` | No | Canonical site URL (used in OG/sitemaps) |
| `NEXT_PUBLIC_PRICE_STREAMER_URL` | No | Public streamer URL for browser connections |
| `STREAMER_PUBLIC_BASE_URL` | No | Docker-internal streamer public URL (used when `RUNNING_IN_DOCKER=true`) |
| `STREAMER_INTERNAL_URL` | No | Streamer internal URL (server components only) |
| `RUNNING_IN_DOCKER` | No | Set to `true` to use Docker-internal API/streamer URLs |
| `NEXT_PUBLIC_CHAIN_ID` | No | Chain ID (default: `2651420`) |
| `NEXT_PUBLIC_CHAIN_NAME` | No | Chain display name (default: `Horizen`) |
| `NEXT_PUBLIC_RPC_URL` | No | JSON-RPC URL (default: Horizen Testnet Caldera) |
| `NEXT_PUBLIC_BLOCK_EXPLORER_URL` | No | Block explorer URL |
| `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` | No | WalletConnect project ID (disables WC if absent) |
| `NEXT_PUBLIC_ZEN_TOKEN_ADDRESS` | No | ZEN token contract address |
| `NEXT_PUBLIC_RELAYER_ESCROW_ADDRESS` | No | RelayerEscrow contract address |
| `NEXT_PUBLIC_GA_MEASUREMENT_ID` | No | Google Analytics measurement ID |
| `NEXT_PUBLIC_GA_SAMPLE_RATE` | No | GA sampling rate 1–100 (production only) |
| `NEXT_DISABLE_MINIFY` | No | Set to `true` to disable production JS minification |
| `FRONTEND_REQUIRE_API` | No | Set to `true` to fail builds/tests when backend is unreachable |
