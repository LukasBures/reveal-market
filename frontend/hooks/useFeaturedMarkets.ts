"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchFeaturedMarkets, type FetchFeaturedMarketsOptions, type MarketSummary } from "@/lib/api";

type UseFeaturedMarketsArgs = {
  limit: number;
  initialData?: MarketSummary[];
} & Pick<FetchFeaturedMarketsOptions, "searchQuery" | "category">;

export function useFeaturedMarkets({ limit, searchQuery, category, initialData }: UseFeaturedMarketsArgs) {
  return useQuery({
    queryKey: ["featuredMarkets", { limit, searchQuery: searchQuery ?? null, category: category ?? null }],
    queryFn: () => fetchFeaturedMarkets(limit, { searchQuery, category }),
    initialData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}
