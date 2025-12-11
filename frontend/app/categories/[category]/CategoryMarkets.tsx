import { fetchFeaturedMarkets } from "@/lib/api";
import { FeaturedMarketsClient } from "@/components/markets/FeaturedMarketsClient";
import { categoryLabelFromSlug, slugify } from "@/lib/slugs";

const MAX_CATEGORY_MARKETS = Number.POSITIVE_INFINITY;
const INITIAL_CATEGORY_BATCH = 20;
export async function CategoryMarkets({ slug }: { slug: string }) {
  const normalizedSlug = slugify(slug);
  const categoryLabel = categoryLabelFromSlug(normalizedSlug) ?? slug;
  let markets = await fetchFeaturedMarkets(INITIAL_CATEGORY_BATCH, {
    category: normalizedSlug,
    status: "active",
    trending: false,
    onlyFeatured: false,
    coalesceGroups: true,
    orderBy: "volume",
  });

  return (
    <div className="glass-panel space-y-4 p-6">
      <FeaturedMarketsClient
        initialMarkets={markets}
        pageSize={INITIAL_CATEGORY_BATCH}
        maxItems={MAX_CATEGORY_MARKETS}
        categoryFilter={categoryLabel}
        emptyNotice="No live markets yet. Check back soon, or hop into another category using the pills above."
        status="active"
        onlyActive
        trending={false}
        sortBy="totalVolume"
      />
    </div>
  );
}
