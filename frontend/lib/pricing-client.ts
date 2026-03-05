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
  payout_zen?: number | null;
  max_stake_zen?: number | null;
  max_user_stake_per_market_zen?: number | null;
  max_market_stake_zen?: number | null;
  remaining_user_stake_zen?: number | null;
  remaining_market_stake_zen?: number | null;
  quote_id?: string | null;
  expires_at?: string | null;
  expiry_ts?: number | null;
  signature?: string | null;
  signer?: string | null;
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
  received_at?: string;
  age_seconds?: number;
  source?: string;
};

export type PriceHistoryPoint = {
  t: number;
  p: number;
};

export type PriceHistoryResponse = {
  history: PriceHistoryPoint[];
  source?: string;
};

export type PriceHistoryInterval = "1m" | "1h" | "6h" | "1d" | "1w" | "max";

export type PriceHistoryOptions = {
  interval?: PriceHistoryInterval;
  fidelity?: number;
  startTs?: number;
  endTs?: number;
  tokenId?: string;
};

import { resolveUrlConfig } from "@/lib/env-presets";

const FX_DEFAULT_PATH = "/fx/zen-usd";

const urls = resolveUrlConfig();
const isServer = typeof window === "undefined";
const apiBase = isServer && urls.apiBaseInternal ? urls.apiBaseInternal : urls.apiBaseUrl;
const streamerBasePublic = urls.streamerPublic;
const streamerBaseInternal = urls.streamerInternal;
const offlineApiBase = "";
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
  const isTestEnv = process.env.NODE_ENV === "test" || process.env.VITEST === "true";
  if (
    tokens.length === 0 &&
    typeof console !== "undefined" &&
    process.env.NODE_ENV !== "production" &&
    !isTestEnv
  ) {
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
        `[pricing-client] STREAMER hosts differ (public=${publicHost}, internal=${internalHost}); align public/internal streamer hosts to avoid CORS/mixed-content issues.`,
      );
    }
  } catch {
    // Ignore URL parse issues here; they will surface when requests are made.
  }
  if (disableStreamerWs) {
    console.warn("[pricing-client] NEXT_PUBLIC_DISABLE_STREAMER_WS is true; forcing SSE fallbacks.");
  }
}

const normalizeFxPath = (path: string) => {
  if (!path) return FX_DEFAULT_PATH;
  if (path.includes("zen-usdc")) return path.replace("zen-usdc", "zen-usd");
  return path;
};

const mapFxPayload = (payload: any): FxQuote => ({
  zen_usd: Number(payload.zen_usd),
  raw_zen_usd: payload.raw_zen_usd !== undefined ? Number(payload.raw_zen_usd) : undefined,
  stale: Boolean(payload.stale),
  received_at: typeof payload.received_at === "string" ? payload.received_at : undefined,
  age_seconds: typeof payload.age_seconds === "number" ? payload.age_seconds : undefined,
  source: typeof payload.source === "string" ? payload.source : undefined,
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

export async function fetchStreamerFxQuote(path = FX_DEFAULT_PATH): Promise<FxQuote> {
  const normalizedPath = normalizeFxPath(path);
  if (mixedContentBlocked) {
    // Browser would block streamer over http on a https page; use API endpoint instead.
    return fetchApiFxQuote();
  }
  try {
    const res = await fetch(getStreamerEndpoint(normalizedPath, true), { cache: "no-store" });
    if (!res.ok) {
      return fetchApiFxQuote();
    }
    const payload = await res.json();
    return mapFxPayload(payload);
  } catch (err) {
    // Fallback to API if streamer is unreachable.
    return fetchApiFxQuote();
  }
}

export async function fetchPricingPreview(
  stakeZen: number,
  opts: { marketId?: string; walletAddress?: string; outcomeId?: number; marketAddress?: string | null },
): Promise<PricingQuote> {
  const userId = opts.walletAddress;
  if (!userId) {
    throw new Error("walletAddress is required for preview quotes");
  }
  const res = await fetch(getEndpoint("/pricing/preview"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      stake_zen: stakeZen,
      market_id: opts.marketId,
      wallet_address: opts.walletAddress,
      outcome_id: opts.outcomeId,
      market_address: opts.marketAddress ?? null,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Preview quote failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as PricingQuote;
}

export async function fetchPricingQuoteWithMeta(
  stakeZen: number,
  opts: {
    marketId?: string;
    walletAddress?: string;
    outcomeId?: number;
    marketAddress?: string;
    walletSignature?: string;
    walletSignatureNonce?: string;
    walletSignatureTimestamp?: number;
  } = {},
): Promise<PricingQuote> {
  if (!opts.walletAddress || opts.outcomeId === undefined || opts.outcomeId === null || !opts.marketId) {
    throw new Error("walletAddress, marketId, and outcomeId are required for signed quotes");
  }
  const normalizedAddress = opts.marketAddress && opts.marketAddress.length > 0 ? opts.marketAddress : null;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.walletSignature) {
    headers["X-Wallet-Signature"] = opts.walletSignature;
  }
  if (opts.walletSignatureNonce) {
    headers["X-Wallet-Signature-Nonce"] = opts.walletSignatureNonce;
  }
  if (typeof opts.walletSignatureTimestamp === "number" && Number.isFinite(opts.walletSignatureTimestamp)) {
    headers["X-Wallet-Signature-Timestamp"] = String(Math.trunc(opts.walletSignatureTimestamp));
  }
  const res = await fetch(getEndpoint("/pricing/quote"), {
    method: "POST",
    headers,
    body: JSON.stringify({
      stake_zen: stakeZen,
      market_id: opts.marketId,
      wallet_address: opts.walletAddress,
      outcome_id: opts.outcomeId,
      market_address: normalizedAddress,
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
  options: PriceHistoryOptions = {},
): Promise<Array<{ timestamp: string; price: string; display_price: string; fx_stale?: boolean }>> {
  if (!marketId) {
    return [];
  }
  const params = new URLSearchParams();
  if (options.interval) {
    params.set("interval", options.interval);
  }
  if (typeof options.fidelity === "number" && Number.isFinite(options.fidelity)) {
    params.set("fidelity", String(options.fidelity));
  }
  if (typeof options.startTs === "number" && Number.isFinite(options.startTs)) {
    params.set("startTs", String(Math.floor(options.startTs)));
  }
  if (typeof options.endTs === "number" && Number.isFinite(options.endTs)) {
    params.set("endTs", String(Math.floor(options.endTs)));
  }
  if (options.tokenId) {
    params.set("token_id", options.tokenId);
  }
  if (Number.isFinite(outcome)) {
    params.set("outcome", String(outcome));
  }
  const query = params.toString();
  const url = getEndpoint(`/markets/${encodeURIComponent(marketId)}/history${query ? `?${query}` : ""}`);
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`History fetch failed: ${res.status}`);
  }
  const payload = (await res.json()) as PriceHistoryResponse;
  const history = Array.isArray(payload?.history) ? payload.history : [];
  return history
    .map((point) => {
      const ts = Number(point.t);
      const price = Number(point.p);
      if (!Number.isFinite(ts) || !Number.isFinite(price)) {
        return null;
      }
      const timestamp = new Date(ts * 1000).toISOString();
      const priceStr = String(price);
      return { timestamp, price: priceStr, display_price: priceStr };
    })
    .filter((entry): entry is { timestamp: string; price: string; display_price: string; fx_stale?: boolean } =>
      Boolean(entry),
    );
}

export type TradeCommitResponse = {
  tx_hash: string;
  quote_id: string;
  market_id: string;
  outcome_id: number;
  stake_zen: number;
  entry_fx: number;
  potential_payout_zen?: number | null;
  status: string;
  ticket_id?: number | null;
  escrow_balance_wei?: number | null;
  salt?: string | null;
  relayer_status?: string | null;
  relayer_job_id?: string | null;
  protocol_topup_zen?: number | null;
  rake_zen?: number | null;
};

const postTradeCommit = async (
  quoteId: string,
  maxFxDiffPercent?: number,
  includeNullFxDiff = false,
  errorLabel = "Trade failed",
  walletAddress?: string,
  walletSignature?: string,
): Promise<TradeCommitResponse> => {
  const payload: Record<string, unknown> = {
    quote_id: quoteId,
    ...(includeNullFxDiff
      ? { max_fx_diff_percent: maxFxDiffPercent ?? null }
      : maxFxDiffPercent !== undefined
        ? { max_fx_diff_percent: maxFxDiffPercent }
        : {}),
  };
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (walletAddress && walletSignature) {
    headers["X-Wallet-Signature"] = walletSignature;
  }
  const res = await fetch(getEndpoint("/trade/commit"), {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${errorLabel} (${res.status}): ${detail}`);
  }
  return (await res.json()) as TradeCommitResponse;
};

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

export function createFxWebSocket(path = FX_DEFAULT_PATH): WebSocket | null {
  const normalizedPath = normalizeFxPath(path);
  if (!shouldUseStreamerWs()) {
    return null;
  }
  try {
    const url = getStreamerWsEndpoint(normalizedPath, true);
    return new WebSocket(url);
  } catch {
    return null;
  }
}

export { FX_DEFAULT_PATH, normalizeFxPath };

export async function submitTrade(
  quoteId: string,
  walletAddress: string,
  walletSignature: string,
  maxFxDiffPercent?: number,
): Promise<TradeCommitResponse> {
  return postTradeCommit(quoteId, maxFxDiffPercent, true, "Trade failed", walletAddress, walletSignature);
}
