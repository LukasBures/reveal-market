# Frontend MVP Checklist

Focus only on the investor-facing gaps that keep the site from reflecting live readiness.

1. **Positions dashboard** – Build a signed-in positions view (stakes, PnL, potential winnings, volume, aggregated stats) with a single “claim winnings” CTA.
2. **Search experience** – Replace the client-only `/markets/search` filtering with a backend search endpoint (keyboard shortcuts, pagination, category pills).
3. **Proof filters + exports** – Add status/verifier/market filters and CSV export to `/proofs`, plus a visible diligence CTA for receipts.
4. **Live market chart** – Wire `MarketDetailChart` to real historical price/liquidity from backend/worker/streamer so every market renders data.
5. **Signed-quote TX flow** – Enforce wallet + market address + outcome id for quotes, reuse a single FX WS, refresh on expiry/chain mismatch, and submit `commitWithQuote` with the signed payload.
6. **Stake limit UX + stale guards** – Surface the 100 ZEN cap and API-provided per-user/per-market caps, and disable transactions when FX/market prices are stale.
7. **CSP/CORS alignment** – Keep `NEXT_PUBLIC_PRICE_STREAMER_URL` aligned with CSP `connect-src` and warn in dev when streamer/API origins are blocked.
8. **Chain defaults** – Keep walletconnect/wagmi envs pinned to Horizen Testnet (2651420) and prompt + fallback on wrong/missing network config.

Everything else can follow once these core experiences are live.
