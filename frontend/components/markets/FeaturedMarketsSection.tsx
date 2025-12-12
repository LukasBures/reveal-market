import { fetchFeaturedMarkets } from "@/lib/api";
import { logger } from "@/lib/logging";
import { serverEnv } from "@/lib/serverEnv";
import type { MarketSortOption } from "@/lib/markets";
import { FeaturedMarketsClient } from "./FeaturedMarketsClient";
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
};

export async function FeaturedMarketsSection({
  pageSize = DEFAULT_PAGE_SIZE,
  maxItems = DEFAULT_MAX_ITEMS,
  searchQuery,
  categoryFilter,
  emptyNotice,
  sortBy = "totalVolume",
}: Props = {}) {
  const orderBy = "volume";
  const initialMarkets = await fetchFeaturedMarkets(pageSize, {
    searchQuery,
    category: categoryFilter,
    status: "active",
    trending: false,
    coalesceGroups: true,
    orderBy,
  });

  if (initialMarkets.length === 0) {
    logger.info("featuredMarkets:empty", {
      pageSize,
      categoryFilter,
      searchQuery,
      apiBase: serverEnv.apiBaseUrl,
    });
  } else {
    logger.debug("featuredMarkets:loaded", {
      count: initialMarkets.length,
      pageSize,
      categoryFilter,
      searchQuery,
    });
  }

  return (
    <FeaturedMarketsClient
      initialMarkets={initialMarkets}
      pageSize={pageSize}
      maxItems={maxItems}
      searchQuery={searchQuery}
      categoryFilter={categoryFilter}
      emptyNotice={emptyNotice}
      status="active"
      onlyActive
      trending={false}
      sortBy={sortBy}
    />
  );
}

export function FeaturedMarketsSkeleton() {
  return (
    <section className="space-y-4">
      <MarketGridSkeleton />
      <div className="flex items-center justify-center">
        <Skeleton className="h-10 w-48 rounded-full border border-white/10 bg-white/10" />
      </div>
    </section>
  );
}
