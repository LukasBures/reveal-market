"use client";

import type { FetchFeaturedMarketsOptions, MarketSummary } from "@/lib/api-types";

type ProxyOptions = Pick<FetchFeaturedMarketsOptions, "searchQuery" | "category" | "offset">;

const buildQuery = (limit: number, options?: ProxyOptions) => {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (typeof options?.offset === "number" && options.offset > 0) {
    params.set("offset", String(options.offset));
  }
  const trimmedSearch = options?.searchQuery?.trim();
  if (trimmedSearch) {
    if (trimmedSearch.length < 2) {
      return null;
    }
    params.set("search", trimmedSearch);
  }
  if (options?.category) {
    params.set("category", options.category);
  }
  return params.toString();
};

export async function fetchMarketsViaProxy(limit: number, options?: ProxyOptions): Promise<MarketSummary[]> {
  const query = buildQuery(limit, options);
  if (query === null) {
    return [];
  }
  const endpoint = `/api/markets/list${query ? `?${query}` : ""}`;
  const response = await fetch(endpoint, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch markets (${response.status})`);
  }
  const payload = await response.json();
  return Array.isArray(payload) ? (payload as MarketSummary[]) : [];
}
