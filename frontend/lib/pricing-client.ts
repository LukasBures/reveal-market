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

import { resolveUrlConfig } from "@/lib/env-presets";

const urls = resolveUrlConfig();
const apiBase = urls.apiBaseInternal || urls.apiBaseUrl;
const streamerBasePublic = urls.streamerPublic;
const streamerBaseInternal = urls.streamerInternal;
const offlineApiBase = "";

const isServer = typeof window === "undefined";
const isBrowser = !isServer;
const isHttpsPage = typeof window !== "undefined" && window.location?.protocol === "https:";
const publicStreamerIsHttp = streamerBasePublic.startsWith("http://");
const publicStreamerIsWs = streamerBasePublic.startsWith("ws://");
// Mixed content is blocked by browsers; detect and gracefully fall back to REST.
const mixedContentBlocked = isBrowser && isHttpsPage && (publicStreamerIsHttp || publicStreamerIsWs);
const disableStreamerWs = process.env.NEXT_PUBLIC_DISABLE_STREAMER_WS === "true";
export const shouldUseStreamerWs = () => !disableStreamerWs && !mixedContentBlocked;
export const priceStreamsDisabled = process.env.NEXT_PUBLIC_DISABLE_PRICE_STREAMS === "true";

const normalizeAssetIds = (tokenIds?: string[]) =>
  (tokenIds ?? [])
    .map((t) => t.trim())
    .filter(Boolean);

const warnMissingAssets = (tokens: string[], transport: "ws" | "sse") => {
  if (tokens.length === 0 && typeof console !== "undefined" && process.env.NODE_ENV !== "production") {
    console.warn(
      `[pricing-client] ${transport} connecting without assets_ids; falling back to market_id placeholder for subscriptions.`,
    );
  }
};

const getEndpoint = (path: string) => `${apiBase}${path}`;
const getStreamerEndpoint = (path: string, preferInternal = false) => {
  if (preferInternal && isServer && streamerBaseInternal) return `${streamerBaseInternal}${path}`;
  return `${streamerBasePublic}${path}`;
};

const toWebSocketScheme = (url: string) => {
  if (url.startsWith("ws://") || url.startsWith("wss://")) return url;
  return url.replace(/^http/, "ws");
};

const getStreamerWsEndpoint = (path: string, preferInternal = false) =>
  toWebSocketScheme(getStreamerEndpoint(path, preferInternal && isServer));

if (typeof console !== "undefined") {
  const parseHost = (value: string) => {
    if (!value) return null;
    try {
      return new URL(value).host;
    } catch {
      try {
        return new URL(`https://${value}`).host;
      } catch {
        return null;
      }
    }
  };
  try {
    const publicHost = parseHost(streamerBasePublic);
    const internalHost = parseHost(streamerBaseInternal) ?? publicHost;
    if (internalHost && publicHost && internalHost !== publicHost && process.env.NODE_ENV !== "production") {
      console.warn(
        `[pricing-client] STREAMER hosts differ (public=${publicHost}, internal=${internalHost}); align NEXT_PUBLIC_PRICE_STREAMER_URL and STREAMER_INTERNAL_URL to avoid CORS/mixed-content issues.`,
      );
    }
  } catch {
    // Ignore URL parse issues here; they will surface when requests are made.
  }
  if (disableStreamerWs) {
    console.warn("[pricing-client] NEXT_PUBLIC_DISABLE_STREAMER_WS is true; forcing SSE fallbacks.");
  }
}

const mapFxPayload = (payload: any): FxQuote => ({
  zen_usd: Number(payload.zen_usd),
  raw_zen_usd: payload.raw_zen_usd !== undefined ? Number(payload.raw_zen_usd) : undefined,
  stale: Boolean(payload.stale),
});

const getApiBases = (): string[] => {
  const bases: string[] = [];
  const env = process.env.NODE_ENV ?? "development";
  bases.push(apiBase);
  if (offlineApiBase && offlineApiBase !== apiBase) {
    bases.push(offlineApiBase);
  }
  if (env !== "production" && typeof window !== "undefined") {
    const origin = window.location?.origin?.replace(/\/$/, "");
    if (origin && !bases.includes(origin)) {
      bases.push(origin);
    }
    const devFallbacks = ["http://localhost:8000", "http://api.localhost"];
    devFallbacks.forEach((base) => {
      if (!bases.includes(base)) bases.push(base);
    });
  }
  return bases;
};

const fetchApiFxQuote = async (): Promise<FxQuote> => {
  const bases = getApiBases();
  let lastError: Error | null = null;
  for (const base of bases) {
    try {
      const res = await fetch(`${base}/pricing/fx`, { cache: "no-store" });
      if (!res.ok) {
        lastError = new Error(`API FX fetch failed: ${res.status}`);
        continue;
      }
      const payload = await res.json();
      return mapFxPayload(payload);
    } catch (err) {
      lastError = err as Error;
    }
  }
  throw lastError || new Error("API FX fetch failed");
};

export async function fetchStreamerFxQuote(path = "/fx/zen-usdc"): Promise<FxQuote> {
  if (mixedContentBlocked) {
    // Browser would block streamer over http on an https page; use API endpoint instead.
    return fetchApiFxQuote();
  }
  try {
    const res = await fetch(getStreamerEndpoint(path, true), { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`FX fetch failed: ${res.status}`);
    }
    const payload = await res.json();
    return mapFxPayload(payload);
  } catch (err) {
    // Fallback to API if streamer is unreachable.
    return fetchApiFxQuote();
  }
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

export function createMarketStream(marketId: string, tokenIds?: string[]): EventSource {
  const params = new URLSearchParams();
  params.set("market_id", marketId);
  const tokens = normalizeAssetIds(tokenIds);
  warnMissingAssets(tokens, "sse");
  if (tokens.length) {
    params.set("assets_ids", tokens.join(","));
  }
  const url = `${getStreamerEndpoint("/stream")}?${params.toString()}`;
  return new EventSource(url);
}

export function createMarketWebSocket(marketId: string, tokenIds?: string[]): WebSocket | null {
  if (!shouldUseStreamerWs()) {
    return null;
  }
  const params = new URLSearchParams();
  params.set("market_id", marketId);
  const tokens = normalizeAssetIds(tokenIds);
  warnMissingAssets(tokens, "ws");
  if (tokens.length) {
    params.set("assets_ids", tokens.join(","));
  }
  const url = `${getStreamerWsEndpoint("/stream/ws", true)}?${params.toString()}`;
  try {
    return new WebSocket(url);
  } catch {
    return null;
  }
}

export function createFxWebSocket(path = "/fx/zen-usdc"): WebSocket | null {
  if (!shouldUseStreamerWs()) {
    return null;
  }
  try {
    const url = getStreamerWsEndpoint(path, true);
    return new WebSocket(url);
  } catch {
    return null;
  }
}
