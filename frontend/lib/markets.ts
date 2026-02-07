import type { MarketSummary } from "./api-types";

const sanitizeNumber = (value: unknown): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export type MarketSortOption = "totalVolume" | "recent" | "popularity";
export type VolumePreference = "24h" | "total";

export const MARKET_CATEGORY_FILTERS = [
  "Crypto",
  "Finance",
  "Sports",
  "Politics",
  "Geopolitics",
  "Tech",
  "Entertainment",
  "Elections",
  "Science",
] as const;

export type MarketCategoryFilter = (typeof MARKET_CATEGORY_FILTERS)[number];

/**
 * Returns a non-negative volume metric. Defaults to 24h volume; `total` uses lifetime volume first.
 */
export const getMarketVolume = (
  market: Pick<MarketSummary, "volume24hUsd" | "orderbookVolumeUsd"> & { volume?: number | null },
  preference: VolumePreference = "24h",
): number => {
  const preferred =
    preference === "total"
      ? market.volume ?? market.orderbookVolumeUsd ?? market.volume24hUsd
      : market.volume24hUsd ?? market.orderbookVolumeUsd ?? market.volume;
  return Math.max(0, sanitizeNumber(preferred));
};

type CommitDeadlineSource = Pick<
  MarketSummary,
  "commitDeadline" | "closesAt" | "ordersOpenedAt" | "startsAt"
> & { createdAt?: string | null };

export const getCommitDeadline = (market: CommitDeadlineSource): string | undefined => {
  const candidates = [
    market.commitDeadline,
    market.closesAt,
    market.ordersOpenedAt,
    market.startsAt,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return undefined;
};

/**
 * Price streams/history are keyed by the Polymarket condition id (CLOB market id).
 * Fall back to the event id when condition id is missing so charts still render.
 */
export const resolvePriceStreamMarketId = (
  market: { conditionId?: string | null; eventId?: string | null },
  fallback?: string,
): string => {
  const candidates = [market.conditionId, market.eventId, fallback];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return "";
};
