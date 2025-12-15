# Frontend MVP Checklist (critical)

Investor-facing gaps that must ship for the MVP. Each item should be validated with `npm run test`, manual QA on `/`, `/categories/*`, `/markets/<eventId>`, and Lighthouse on mobile + desktop.

1. **Positions dashboard (wallet-connected)**  
   - Fetch positions from backend/streamer subgraph proxy; show stakes, cost basis, PnL, potential winnings, volume, and aggregated stats.  
   - Single “Claim winnings” CTA that batches eligible claims (or deep-links to relayer) and surfaces error states; include loading/success toasts and retry.  
   - Empty/error states, pagination, and responsive layout tested on mobile/desktop; add Vitest coverage for data merge and claim CTA disablement.

2. **Backend-powered search**  
   - `/markets/search` must call the backend search endpoint with pagination + category/tag pills; no client-only filtering.  
   - Keyboard shortcuts (focus, submit, clear), recent searches, and SSR cache tags that match worker invalidation.  
   - Tests for pagination + debounce + empty state; ensure search suggestions still route through `/app/api/markets/suggest`.

3. **Proofs filtering + export**  
   - `/proofs` adds filters (status, verifier, market/event/condition) and CSV export of the current view.  
   - Include “diligence” CTA linking to backend/prover docs; keep infinite scroll + manual load more.  
   - Tests for filter chips, CSV headers, and persistence in query params.

4. **Live market chart**  
   - `MarketDetailChart` renders real history from backend/streamer (price + liquidity) with no placeholder data; handles empty history gracefully.  
   - Show FX staleness/warnings; allow timeframe toggles; streaming updates should merge into the chart without jitter.  
   - Tests for history fetch, empty states, and streaming merge.

5. **Signed-quote flow**  
   - Enforce wallet + market address + outcome id before calling `/pricing/quote`; reuse a single FX WS connection.  
   - Auto-refresh quotes on expiry/chain mismatch; wire wagmi/viem `commitWithQuote` submission and show pending/success/error states.  
   - Tests for FX stale guard, expiry refresh, and digest mismatch handling.

6. **Stake limits & stale guards**  
   - Surface 0.1 ZEN cap and API per-user/per-market caps; disable submit when caps or FX/market staleness hit.  
   - Show explainer tooltips for caps and stale data; add Vitest coverage for guard rails in `StakeQuoteCard` and friends.

7. **CSP/CORS alignment**  
   - Keep streamer/API hosts aligned with CSP `connect-src`; warn in dev when hosts are blocked.  
   - Update `next.config.mjs` before adding new domains/assets; add a test or lint rule to prevent missing CSP entries.

8. **Chain defaults & safety rails**  
   - WalletConnect/wagmi envs pinned to Horizen Testnet (2651420); prompt to switch/fallback when network mismatched.  
   - UX copy for wrong network/offline streamer/API; ensure buttons disable instead of throwing uncaught errors.

## Nice to have (post-MVP)

- Marketing polish: copy tone, illustrations, motion once flows above are live.
- Expanded search facets (tags, recency, liquidity) and saved searches + persistence.
- Mobile-first refinements for dashboard/proofs layouts and navigation.
- Additional analytics/observability for conversion + error funnels (errors, streamer/API reachability).

## Production hardening

- Performance budgets and bundle audits (LCP/TTI, font loading, streaming caches).
- SLOs + alerting for frontend error rates and streamer/API reachability.
- Accessibility sweep (keyboard traps, focus states, semantic landmarks, high contrast).
- Incident playbooks and status messaging for streamer/API/FX outages.
