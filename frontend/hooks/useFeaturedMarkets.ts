"use client";

import { useQuery } from "@tanstack/react-query";

import type { FetchFeaturedMarketsOptions, MarketSummary } from "@/lib/api-types";
import { loadFeaturedMarketsAction } from "@/app/actions/markets";

type UseFeaturedMarketsArgs = {
  limit: number;
  initialData?: MarketSummary[];
} & Pick<FetchFeaturedMarketsOptions, "searchQuery" | "category">;

export function useFeaturedMarkets({ limit, searchQuery, category, initialData }: UseFeaturedMarketsArgs) {
  return useQuery({
    queryKey: ["featuredMarkets", { limit, searchQuery: searchQuery ?? null, category: category ?? null }],
    queryFn: () => loadFeaturedMarketsAction(limit, { searchQuery, category }),
    initialData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}
