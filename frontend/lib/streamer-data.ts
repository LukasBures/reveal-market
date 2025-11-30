import { resolveUrlConfig } from "@/lib/env-presets";
import { logger } from "@/lib/logging";

type OrderbookAggregate = {
  id: string;
  tradesQuantity?: number;
  buysQuantity?: number;
  sellsQuantity?: number;
  collateralVolume?: number;
  scaledCollateralVolume?: number;
  collateralBuyVolume?: number;
  scaledCollateralBuyVolume?: number;
  collateralSellVolume?: number;
  scaledCollateralSellVolume?: number;
  volume24h?: number;
};

const { streamerPublic, streamerInternal } = resolveUrlConfig();

const getStreamerBase = (preferInternal = false) => {
  if (preferInternal) return streamerInternal || streamerPublic;
  return streamerPublic;
};

const safeNumber = (value: unknown): number | undefined => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const chunk = <T>(arr: T[], size: number): T[][] => {
  const result: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    result.push(arr.slice(i, i + size));
  }
  return result;
};

export async function fetchOrderbookAggregates(tokenIds: string[]): Promise<Record<string, OrderbookAggregate>> {
  const unique = Array.from(new Set(tokenIds.map((t) => t.trim()).filter(Boolean)));
  if (!unique.length) return {};
  const base = getStreamerBase(true);
  const results: Record<string, OrderbookAggregate> = {};
  const batches = chunk(unique, 20);
  for (const batch of batches) {
    const params = new URLSearchParams();
    params.set("ids", batch.join(","));
    const url = `${base}/data/subgraph/markets?${params.toString()}`;
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) {
        logger.warn("streamer.orderbook.fetch_failed", { status: res.status, url });
        continue;
      }
      const payload = await res.json();
      const data = Array.isArray(payload.data) ? payload.data : payload.data?.orderbooks ?? [];
      for (const entry of data) {
        const id = String(entry.id ?? "").trim();
        if (!id) continue;
        results[id] = {
          id,
          tradesQuantity: safeNumber(entry.tradesQuantity),
          buysQuantity: safeNumber(entry.buysQuantity),
          sellsQuantity: safeNumber(entry.sellsQuantity),
          collateralVolume: safeNumber(entry.collateralVolume),
          scaledCollateralVolume: safeNumber(entry.scaledCollateralVolume),
          collateralBuyVolume: safeNumber(entry.collateralBuyVolume),
          scaledCollateralBuyVolume: safeNumber(entry.scaledCollateralBuyVolume),
          collateralSellVolume: safeNumber(entry.collateralSellVolume),
          scaledCollateralSellVolume: safeNumber(entry.scaledCollateralSellVolume),
          volume24h: safeNumber(entry.volume24h ?? entry.volume24H ?? entry.volume_24h),
        };
      }
    } catch (error) {
      logger.warn("streamer.orderbook.fetch_error", { error: (error as Error).message, url });
    }
  }
  return results;
}

export async function fetchOpenInterest(conditionId: string): Promise<number | undefined> {
  const normalized = conditionId.trim();
  if (!normalized) return undefined;
  const base = getStreamerBase(true);
  const params = new URLSearchParams();
  params.set("market_id", normalized);
  const url = `${base}/data/subgraph/open-interest?${params.toString()}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      logger.warn("streamer.oi.fetch_failed", { status: res.status, url });
      return undefined;
    }
    const payload = await res.json();
    const first = Array.isArray(payload.data) ? payload.data[0] : (payload.data?.[0] ?? null);
    const amount = first?.amount ?? first?.openInterestUSD ?? first?.openInterest ?? null;
    return safeNumber(amount);
  } catch (error) {
    logger.warn("streamer.oi.fetch_error", { error: (error as Error).message, url });
    return undefined;
  }
}

export async function fetchMarketTokens(conditionId: string, { first = 50 }: { first?: number } = {}): Promise<string[]> {
  const normalized = conditionId.trim();
  if (!normalized) return [];
  const base = getStreamerBase(true);
  const params = new URLSearchParams();
  params.set("condition", normalized);
  params.set("first", String(Math.max(1, Math.min(200, first))));
  const url = `${base}/data/subgraph/market-data?${params.toString()}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      logger.warn("streamer.marketdata.fetch_failed", { status: res.status, url });
      return [];
    }
    const payload = await res.json();
    const rows = Array.isArray(payload.data) ? payload.data : payload.data?.marketDatas ?? [];
    const ids = rows
      .map((row: { id?: string }) => String(row.id ?? "").trim())
      .filter((id: string) => Boolean(id));
    return Array.from(new Set(ids));
  } catch (error) {
    logger.warn("streamer.marketdata.fetch_error", { error: (error as Error).message, url });
    return [];
  }
}

export type ActivityEntry = {
  id: string;
  type: "split" | "merge" | "redemption";
  timestamp?: string;
  account?: string;
  condition?: string;
  amount?: number;
  payout?: number;
  indexSets?: string[];
};

export async function fetchMarketActivity(
  conditionId: string,
  { limit = 20 }: { limit?: number } = {},
): Promise<ActivityEntry[]> {
  const normalized = conditionId.trim();
  if (!normalized) return [];
  const base = getStreamerBase(true);
  const params = new URLSearchParams();
  params.set("condition", normalized);
  params.set("first", String(Math.max(1, Math.min(100, limit))));
  const url = `${base}/data/subgraph/activity?${params.toString()}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      logger.warn("streamer.activity.fetch_failed", { status: res.status, url });
      return [];
    }
    const payload = await res.json();
    const data = payload?.data || {};
    const entries: ActivityEntry[] = [];
    for (const split of data.splits || []) {
      entries.push({
        id: String(split.id ?? ""),
        type: "split",
        timestamp: split.timestamp,
        account: split.stakeholder,
        condition: split.condition,
        amount: safeNumber(split.amount),
      });
    }
    for (const merge of data.merges || []) {
      entries.push({
        id: String(merge.id ?? ""),
        type: "merge",
        timestamp: merge.timestamp,
        account: merge.stakeholder,
        condition: merge.condition,
        amount: safeNumber(merge.amount),
      });
    }
    for (const redemption of data.redemptions || []) {
      entries.push({
        id: String(redemption.id ?? ""),
        type: "redemption",
        timestamp: redemption.timestamp,
        account: redemption.redeemer,
        condition: redemption.condition,
        payout: safeNumber(redemption.payout),
        indexSets: Array.isArray(redemption.indexSets) ? redemption.indexSets.map(String) : undefined,
      });
    }
    return entries.sort((a, b) => {
      const ta = a.timestamp ? Number(a.timestamp) : 0;
      const tb = b.timestamp ? Number(b.timestamp) : 0;
      return tb - ta;
    });
  } catch (error) {
    logger.warn("streamer.activity.fetch_error", { error: (error as Error).message, url });
    return [];
  }
}
