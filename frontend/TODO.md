# Frontend MVP Checklist (critical)

Investor-facing gaps that must ship for the MVP. Each item should be validated with `npm run test`, manual QA on `/`, `/markets/search`, `/markets/<eventId>`, `/dashboard`, and Lighthouse on mobile + desktop.

1. **Proofs filters + CSV export**
   - Build filter UI for `market_id`, `event_id`, `condition_id`, and `request_id` (add status/verifier once the API exposes them).
   - Add CSV export for the current filter view and a diligence CTA linking to prover docs.
   - Tests for filter persistence, CSV headers, and export payload.

2. **/markets/search refinements**
   - Add category/status chips with query-param persistence; ensure backend search remains the source of truth.
   - Add keyboard shortcuts (`/` or Cmd/Ctrl+K) plus recent-search memory.
   - Tests for pagination + filters + shortcut focus.

3. **Streamer/API visibility guardrails**
   - Add a user-facing banner when FX/streamer is stale, blocked, or `priceStreamsDisabled` is true.
   - Dev-only warning when configured API/streamer origins don't match CSP/connect-src expectations.
   - Tests for banner visibility toggles.

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
