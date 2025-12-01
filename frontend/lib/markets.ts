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
