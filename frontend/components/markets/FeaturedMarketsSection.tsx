import { fetchFeaturedMarkets } from "@/lib/api";
import { FeaturedMarketsClient, DEFAULT_MAX_ITEMS, DEFAULT_PAGE_SIZE } from "./FeaturedMarketsClient";
import { MarketGridSkeleton } from "./MarketGridSkeleton";
import { Skeleton } from "../ui/Skeleton";

type Props = {
  pageSize?: number;
  maxItems?: number;
  searchQuery?: string;
  categoryFilter?: string;
  tagFilter?: string;
};

export async function FeaturedMarketsSection({
  pageSize = DEFAULT_PAGE_SIZE,
  maxItems = DEFAULT_MAX_ITEMS,
  searchQuery,
  categoryFilter,
  tagFilter,
}: Props) {
  const initialMarkets = await fetchFeaturedMarkets(pageSize, {
    searchQuery,
    category: categoryFilter,
    tag: tagFilter,
  });

  return (
    <FeaturedMarketsClient
      initialMarkets={initialMarkets}
      pageSize={pageSize}
      maxItems={maxItems}
      searchQuery={searchQuery}
      categoryFilter={categoryFilter}
      tagFilter={tagFilter}
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
