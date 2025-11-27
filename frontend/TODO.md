# Frontend MVP Checklist

Focus only on the investor-facing gaps that keep the site from reflecting live readiness.

1. **Live market chart** – Replace the mocked `MarketDetailChart` with historical price/liquidity pulled from the backend/worker so every market page visualizes real data.
2. **Search experience** – Ship a `/markets/search` route (keyboard shortcuts, pagination, category pills) that queries the backend search endpoint instead of filtering placeholder cards.
3. **Proof filters + exports** – Add status/verifier/market filters and CSV export to `/proofs`, plus a visible diligence CTA so investors can grab receipts immediately.
4. **Bet limit UX + stale guards** – Keep the 100 ZEN per-bet cap surfaced in stake inputs, show per-user/per-market caps once exposed by the API, and disable betting when FX/market prices are stale (follow `/stream`/`/health` flags).
5. **CSP/CORS alignment** – Keep `NEXT_PUBLIC_PRICE_STREAMER_URL` + CSP connect-src in sync, and surface a warning in dev when streamer/API origins aren’t allowed.
6. **Signed-quote TX flow** – Ensure the client always requests quotes with wallet + market address + outcome id, reuses a single FX WS connection, and submits `commitWithQuote` with the signed payload (refreshing on expiry/chain mismatch).
7. **Chain defaults** – Keep walletconnect/wagmi envs aligned to Horizen Testnet (chain id `2651420`, RPC `https://horizen-testnet.rpc.caldera.xyz/http`, explorer `https://horizen-testnet.explorer.caldera.xyz`); surface a wrong-network prompt and fallback when envs are missing.

Everything else can follow once these three experiences are live.
