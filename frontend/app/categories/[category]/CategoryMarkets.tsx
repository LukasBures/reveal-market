import { fetchFeaturedMarkets } from "@/lib/api";
import type { MarketSummary } from "@/lib/api-types";
import { MarketGrid } from "@/components/markets/MarketGrid";
import { slugify } from "@/lib/slugs";

const MAX_CATEGORY_MARKETS = 60;
const FALLBACK_MULTIPLIER = 2;

function filterByCategory(markets: MarketSummary[], categorySlug: string) {
  const normalized = slugify(categorySlug);
  return markets.filter((market) => slugify(market.category ?? "") === normalized);
}

export async function CategoryMarkets({ slug }: { slug: string }) {
  const normalizedSlug = slugify(slug);
  let notice: string | null = null;
  let markets = await fetchFeaturedMarkets(MAX_CATEGORY_MARKETS, { category: normalizedSlug });

  if (markets.length === 0) {
    const fallbackPool = await fetchFeaturedMarkets(MAX_CATEGORY_MARKETS * FALLBACK_MULTIPLIER);
    const filtered = filterByCategory(fallbackPool, normalizedSlug);
    if (filtered.length > 0) {
      markets = filtered.slice(0, MAX_CATEGORY_MARKETS);
    } else if (fallbackPool.length > 0) {
      notice = "Category feed is still syncing, so featured markets are shown instead.";
      markets = fallbackPool.slice(0, MAX_CATEGORY_MARKETS);
    }
  }

  if (markets.length === 0) {
    return (
      <div className="glass-panel p-8 text-center text-slate-300">
        <p className="text-lg font-semibold text-white">No live markets yet</p>
        <p className="mt-2 text-sm text-slate-400">Check back soon, or hop into another category using the pills above.</p>
      </div>
    );
  }

  return (
    <div className="glass-panel space-y-4 p-6">
      {notice && (
        <div className="rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          {notice}
        </div>
      )}
      <MarketGrid markets={markets} />
    </div>
  );
}
