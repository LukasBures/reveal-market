"use client";

import { useQuery } from "@tanstack/react-query";

import type { EventSummary, FetchFeaturedMarketsOptions } from "@/lib/api-types";
import { loadFeaturedEventsAction } from "@/app/actions/events";

type UseFeaturedMarketsArgs = {
  limit: number;
  initialData?: EventSummary[];
} & Pick<
  FetchFeaturedMarketsOptions,
  "searchQuery" | "category" | "status" | "trending" | "orderBy" | "closesWithinHours"
>;

export function useFeaturedEvents({
  limit,
  searchQuery,
  category,
  status,
  trending,
  closesWithinHours,
  orderBy,
  initialData,
}: UseFeaturedMarketsArgs) {
  const normalizedStatus = status ?? "active";
  const normalizedOrderBy = orderBy ?? "volume";
  return useQuery({
    queryKey: [
      "featuredEvents",
      {
        limit,
        searchQuery: searchQuery ?? null,
        category: category ?? null,
        status: normalizedStatus,
        trending: trending ?? null,
        coalesceGroups: true,
        orderBy: normalizedOrderBy,
        closesWithinHours: closesWithinHours ?? null,
      },
    ],
    queryFn: () =>
      loadFeaturedEventsAction(limit, {
        searchQuery,
        category,
        status: normalizedStatus,
        trending,
        coalesceGroups: true,
        orderBy: normalizedOrderBy,
        closesWithinHours,
      }),
    initialData,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}
