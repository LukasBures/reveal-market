import type { MarketSummary } from "./api-types";

const sanitizeNumber = (value: unknown): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export const getMarketVolume = (
  market: Pick<MarketSummary, "volume24hUsd" | "orderbookVolumeUsd">,
): number => {
  const volume = market.volume24hUsd ?? market.orderbookVolumeUsd;
  return Math.max(0, sanitizeNumber(volume));
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
