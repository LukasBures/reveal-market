# Frontend MVP Checklist (critical)

Investor-facing gaps that must ship for the MVP. Each item should be validated with `npm run test`, manual QA on `/`, `/markets/search`, `/markets/<eventId>`, `/dashboard`, and Lighthouse on mobile + desktop.

## Nice to have (post-MVP)

- Streamer/API visibility guardrails: add a user-facing banner when FX/streamer is stale, blocked, or `priceStreamsDisabled` is true; add dev-only CSP/connect-src warnings; include tests for banner visibility toggles.
- Proof receipts UX: group multi-batch proofs per market, show batch root/index metadata, and add filtering on `/proofs`.
- Marketing polish: copy tone, illustrations, motion once flows above are live.
- Expanded search facets (tags, recency, liquidity) and saved searches + persistence.
- Mobile-first refinements for dashboard/proofs layouts and navigation.
- Additional analytics/observability for conversion + error funnels (errors, streamer/API reachability).

## Production hardening

- Performance budgets and bundle audits (LCP/TTI, font loading, streaming caches).
- SLOs + alerting for frontend error rates and streamer/API reachability.
- Accessibility sweep (keyboard traps, focus states, semantic landmarks, high contrast).
- Incident playbooks and status messaging for streamer/API/FX outages.
