"use server";

import type { FetchFeaturedMarketsOptions, MarketSummary } from "@/lib/api-types";
import { fetchFeaturedMarkets } from "@/lib/api";

export async function loadFeaturedMarketsAction(
  limit: number,
  options?: FetchFeaturedMarketsOptions,
): Promise<MarketSummary[]> {
  return fetchFeaturedMarkets(limit, options);
}
