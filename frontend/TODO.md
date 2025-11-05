# Frontend TODO & Roadmap

This document outlines the initial build plan for the Reveal Market front-end. Focus on delivering a functional market explorer tied to the new backend APIs, then layering on richer features and polish.

## Phase 1 – MVP (read-only experience)

- **Scaffold app shell**  
  Set up the chosen framework (e.g. Next.js + TypeScript + Tailwind). Include baseline routing, shared layout with header/footer, global styles, and theming tokens.

- **Environment + API client plumbing**  
  Add configuration helpers for backend base URLs and feature flags. Implement a typed API client for `/markets`, `/markets/{id}`, `/markets/stats`, and `/resolution/{condition}` with error handling and request logging (e.g. via React Query/SWR).

- **Markets index page**  
  Display paginated market cards showing title, status, category, latest prices, rake, image, and resolution status (using the new resolution endpoint). Support filtering by status/category/oracle and text search, reusing backend query params.

- **Market detail view**  
  Render full metadata: outcomes with price chart/snapshot, conditional tokens payout vector, commit/reveal deadlines, guardian info, and related links. Surface resolution summary (winner, payouts, checkedAt) prominently once available.

- **Skeleton/loading + error states**  
  Implement consistent placeholders for list/detail views, and actionable error boundaries for API failures (retry, contact support).

## Phase 2 – Interactivity & user tooling

- **Watchlist / bookmarks**  
  Allow users to save markets locally (localStorage) and surface a dedicated “My Markets” view.

- **On-chain transaction helpers**  
  Integrate a wallet connector (e.g., wagmi/viem) to provide “commit” and “claim refund” interactions initially, respecting commit/reveal phases. Display gas estimates and success toasts.

- **Resolution transparency**  
  Add a timeline component showing Gamma “closed/resolved” markers alongside on-chain payout detection (block number, tx hash). Offer downloadable JSON/CSV of resolution data for auditors.

- **Stats dashboard**  
  Expand `/markets/stats` into charts (status breakdown, rake distribution), and add high-level metrics (total markets, resolved vs pending).

## Phase 3 – Operational polish

- **Live updates**  
  Set up SSE/websocket or polling to auto-refresh market cards when the worker sync detects changes, minimizing manual refreshes.

- **Admin utilities**  
  Provide a hidden admin view for operators: manual cache invalidation triggers, resolution diagnostics (show raw Conditional Tokens payout vector), and links to foundry/forge scripts for settlement.

- **Internationalization & accessibility**  
  Internationalize copy, add keyboard navigation, and verify color contrast against accessibility guidelines.

- **Testing & CI**  
  Add Playwright/Cypress flows for market list/detail pages, unit tests for hooks/utilities, and wire the suite into GitHub Actions. Include Lighthouse budget checks to keep performance acceptable.

## Cross-cutting concerns

- **Design system**  
  Formalize a UI kit (buttons, chips, cards) to keep the experience consistent across pages, mirroring backend data naming (status, resolution, rake).

- **Documentation**  
  Update the main README with front-end bootstrapping instructions, required env vars (`NEXT_PUBLIC_API_BASE_URL` etc.), and release checklist (run tests, bump snapshots).

Progress through these phases sequentially; ensure Phase 1 is production-stable before enabling user transactions or live updates. Revisit items in `backend/TODO.md` to stay aligned (e.g., resolution persistence, rake override surfacing). 

