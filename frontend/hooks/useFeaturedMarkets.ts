"use client";

import { useQuery } from "@tanstack/react-query";

import type { FetchFeaturedMarketsOptions, MarketSummary } from "@/lib/api-types";
import { loadFeaturedMarketsAction } from "@/app/actions/markets";

type UseFeaturedMarketsArgs = {
  limit: number;
  initialData?: MarketSummary[];
} & Pick<FetchFeaturedMarketsOptions, "searchQuery" | "category" | "status" | "trending">;

export function useFeaturedMarkets({ limit, searchQuery, category, status, trending, initialData }: UseFeaturedMarketsArgs) {
  const normalizedStatus = status ?? "active";
  return useQuery({
    queryKey: [
      "featuredMarkets",
      { limit, searchQuery: searchQuery ?? null, category: category ?? null, status: normalizedStatus, trending: trending ?? null },
    ],
    queryFn: () => loadFeaturedMarketsAction(limit, { searchQuery, category, status: normalizedStatus, trending }),
    initialData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}
