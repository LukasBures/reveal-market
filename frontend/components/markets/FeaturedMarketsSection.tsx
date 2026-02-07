import { fetchFeaturedEvents } from "@/lib/api";
import { logger } from "@/lib/logging";
import { serverEnv } from "@/lib/serverEnv";
import type { MarketSortOption } from "@/lib/markets";
import { FeaturedEventsClient } from "./FeaturedMarketsClient";
import { DEFAULT_MAX_ITEMS, DEFAULT_PAGE_SIZE } from "./constants";
import { MarketGridSkeleton } from "./MarketGridSkeleton";
import { Skeleton } from "../ui/Skeleton";

type Props = {
  pageSize?: number;
  maxItems?: number;
  searchQuery?: string;
  categoryFilter?: string;
  emptyNotice?: string;
  sortBy?: MarketSortOption;
  status?: string;
  onlyActive?: boolean;
};

export async function FeaturedEventsSection({
  pageSize = DEFAULT_PAGE_SIZE,
  maxItems = DEFAULT_MAX_ITEMS,
  searchQuery,
  categoryFilter,
  emptyNotice,
  sortBy = "totalVolume",
  status = "active",
  onlyActive = true,
}: Props = {}) {
  const orderBy = sortBy === "recent" ? "recent" : sortBy === "popularity" ? "popularity" : "volume";
  const initialMarkets = await fetchFeaturedEvents(pageSize, {
    searchQuery,
    category: categoryFilter,
    status,
    trending: false,
    orderBy,
  });

  if (initialMarkets.length === 0) {
    logger.info("featuredEvents:empty", {
      pageSize,
      categoryFilter,
      searchQuery,
      apiBase: serverEnv.apiBaseUrl,
    });
  } else {
    logger.debug("featuredEvents:loaded", {
      count: initialMarkets.length,
      pageSize,
      categoryFilter,
      searchQuery,
    });
  }

  return (
    <FeaturedEventsClient
      initialMarkets={initialMarkets}
      pageSize={pageSize}
      maxItems={maxItems}
      searchQuery={searchQuery}
      categoryFilter={categoryFilter}
      emptyNotice={emptyNotice}
      status={status}
      onlyActive={onlyActive}
      trending={false}
      sortBy={sortBy}
    />
  );
}

export function FeaturedEventsSkeleton() {
  return (
    <section className="space-y-4">
      <MarketGridSkeleton />
      <div className="flex items-center justify-center">
        <Skeleton className="h-10 w-48 rounded-full border border-white/10 bg-white/10" />
      </div>
    </section>
  );
}
