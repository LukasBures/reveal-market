export type PricingQuote = {
  stake_zen: number;
  stake_wei: string | number;
  zen_usd: number;
  zen_usd_scaled: string | number;
  displayed_odds_multiplier: number;
  rake_zen: number;
  refund_zen: number;
  hedge_usdc: number;
  haircut_percent: number;
  worsen_percent: number;
  rake_percent: number;
  total_monetisation: number;
  chain_id: number;
  max_stake_zen?: number | null;
  max_user_stake_per_market_zen?: number | null;
  max_market_stake_zen?: number | null;
  remaining_user_stake_zen?: number | null;
  remaining_market_stake_zen?: number | null;
  quote_id: string;
  expires_at: string;
  expiry_ts: number;
  signature: string;
  signer: string;
  market_id?: string | null;
  user_id?: string | null;
  wallet_address?: string | null;
  outcome_id?: number | null;
  market_address?: string | null;
};

export type FxQuote = {
  zen_usd: number;
  raw_zen_usd?: number;
  stale: boolean;
};

const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/$/, "");
const streamerBasePublic = (process.env.NEXT_PUBLIC_PRICE_STREAMER_URL || "").replace(/\/$/, "");
const streamerBaseInternal = (process.env.STREAMER_INTERNAL_URL || "").replace(/\/$/, "");

const getEndpoint = (path: string) => `${apiBase || "http://localhost:8000"}${path}`;
const getStreamerEndpoint = (path: string, preferInternal = false) => {
  if (preferInternal && streamerBaseInternal) return `${streamerBaseInternal}${path}`;
  return `${streamerBasePublic || "http://localhost:8100"}${path}`;
};

const toWebSocketScheme = (url: string) => {
  if (url.startsWith("ws://") || url.startsWith("wss://")) return url;
  return url.replace(/^http/, "ws");
};

const getStreamerWsEndpoint = (path: string, preferInternal = false) =>
  toWebSocketScheme(getStreamerEndpoint(path, preferInternal));

export async function fetchStreamerFxQuote(path = "/fx/zen-usdc"): Promise<FxQuote> {
  const res = await fetch(getStreamerEndpoint(path, true), { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`FX fetch failed: ${res.status}`);
  }
  const payload = await res.json();
  return {
    zen_usd: Number(payload.zen_usd),
    raw_zen_usd: payload.raw_zen_usd ? Number(payload.raw_zen_usd) : undefined,
    stale: Boolean(payload.stale),
  };
}

export async function fetchFxQuote(): Promise<FxQuote> {
  const res = await fetch(getEndpoint("/pricing/fx"), { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`FX fetch failed: ${res.status}`);
  }
  return (await res.json()) as FxQuote;
}

export async function fetchPricingQuote(
  stakeZen: number,
  opts: { walletAddress: string; marketAddress: string; outcomeId: number; marketId?: string; userId?: string },
): Promise<PricingQuote> {
  return fetchPricingQuoteWithMeta(stakeZen, opts);
}

export async function fetchPricingQuoteWithMeta(
  stakeZen: number,
  opts: { marketId?: string; userId?: string; walletAddress?: string; outcomeId?: number; marketAddress?: string } = {},
): Promise<PricingQuote> {
  if (!opts.walletAddress || !opts.marketAddress || opts.outcomeId === undefined || opts.outcomeId === null) {
    throw new Error("walletAddress, marketAddress, and outcomeId are required for signed quotes");
  }
  const res = await fetch(getEndpoint("/pricing/quote"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      stake_zen: stakeZen,
      market_id: opts.marketId,
      user_id: opts.userId,
      wallet_address: opts.walletAddress,
      outcome_id: opts.outcomeId,
      market_address: opts.marketAddress,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Quote failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as PricingQuote;
}

export async function fetchPriceHistory(
  marketId: string,
  outcome: number,
  limit = 200,
): Promise<Array<{ timestamp: string; price: string; display_price: string; fx_stale?: boolean }>> {
  const res = await fetch(
    getStreamerEndpoint(`/history?market_id=${encodeURIComponent(marketId)}&outcome=${outcome}&limit=${limit}`, true),
    {
      cache: "no-store",
    },
  );
  if (!res.ok) {
    throw new Error(`History fetch failed: ${res.status}`);
  }
  const payload = await res.json();
  return Array.isArray(payload.data) ? payload.data : [];
}

export function createMarketStream(marketId: string): EventSource {
  const url = `${getStreamerEndpoint("/stream")}?market_id=${encodeURIComponent(marketId)}`;
  return new EventSource(url);
}

export function createFxWebSocket(path = "/fx/zen-usdc"): WebSocket {
  const url = getStreamerWsEndpoint(path, true);
  return new WebSocket(url);
}
