export type PricingQuote = {
  stake_zen: number;
  zen_usd: number;
  displayed_odds_multiplier: number;
  rake_zen: number;
  refund_zen: number;
  hedge_usdc: number;
  haircut_percent: number;
  worsen_percent: number;
  rake_percent: number;
  total_monetisation: number;
};

export type FxQuote = {
  zen_usd: number;
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

export async function fetchFxQuote(): Promise<FxQuote> {
  const res = await fetch(getEndpoint("/pricing/fx"), { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`FX fetch failed: ${res.status}`);
  }
  return (await res.json()) as FxQuote;
}

export async function fetchPricingQuote(stakeZen: number, zenUsd: number): Promise<PricingQuote> {
  const res = await fetch(getEndpoint("/pricing/quote"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stake_zen: stakeZen, zen_usd: zenUsd }),
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

export function createPriceStream(marketId: string): EventSource {
  const url = `${getStreamerEndpoint("/stream")}?market_id=${encodeURIComponent(marketId)}`;
  return new EventSource(url);
}
