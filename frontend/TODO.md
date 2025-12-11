# Frontend MVP Checklist (critical)

Investor-facing gaps that must ship for the MVP:

1. **Positions dashboard** – Connected wallets see stakes, PnL, potential winnings, volume, aggregated stats, and a single “claim winnings” CTA.
2. **Backend search** – `/markets/search` uses the backend search endpoint with pagination, category pills, and keyboard shortcuts (no client-only filtering).
3. **Proof filters + CSV** – `/proofs` supports status/verifier/market filters, CSV export, and a visible diligence CTA for receipts.
4. **Live market chart** – `MarketDetailChart` renders backend/worker/streamer history + liquidity for every market (no placeholder data).
5. **Signed-quote flow** – Enforce wallet + market address + outcome id, reuse one FX WS, refresh on expiry/chain mismatch, and submit `commitWithQuote` with the signed payload.
6. **Stake limits & stale guards** – Surface the 0.1 ZEN cap and API per-user/per-market caps; block transactions when FX/market data is stale.
7. **CSP/CORS alignment** – Keep streamer/API hosts aligned with CSP `connect-src`; warn in dev when hosts are blocked; update CSP before adding new domains/assets.
8. **Chain defaults** – Keep walletconnect/wagmi envs pinned to Horizen Testnet (2651420) and prompt/fallback on wrong or missing network config.

## Nice to have (post-MVP)

- Docs/marketing polish (copy tone, illustrations, motion) once critical flows are live.
- Expanded search facets (tags, recency, liquidity) and saved searches.
- Mobile-first refinements for dashboard/proofs layouts and navigation.
- Additional analytics/observability for conversion + error funnels.

## Production hardening

- Performance budgets and bundle audits (LCP/TTI, font loading, streaming caches).
- SLOs + alerting for frontend error rates and streamer/API reachability.
- Accessibility sweep (keyboard traps, focus states, semantic landmarks, high contrast).
- Incident playbooks and status messaging for streamer/API/fx outages.
