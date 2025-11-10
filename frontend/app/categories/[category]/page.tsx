import type { Metadata } from "next";
import { Suspense } from "react";
import { fetchFeaturedMarkets } from "@/lib/api";
import { MarketGrid } from "@/components/markets/MarketGrid";
import { MarketGridSkeleton } from "@/components/markets/MarketGridSkeleton";
import { notFound } from "next/navigation";
import { buildMetadata } from "@/lib/seo";
import { categorySlugs, parseCategorySlug } from "@/lib/slugs";

type CategoryPageProps = {
  params: Promise<{ category: string }>;
};

const MAX_CATEGORY_MARKETS = 60;
export function generateStaticParams() {
  return categorySlugs.map((category) => ({ category }));
}

export async function generateMetadata({ params }: CategoryPageProps): Promise<Metadata> {
  const { category } = await params;
  const parsed = parseCategorySlug(category);
  if (!parsed) {
    return buildMetadata({
      title: "Categories | Reveal Market",
      description: "Explore curated market categories.",
      path: "/categories",
    });
  }
  return buildMetadata({
    title: `${parsed.label} Markets | Reveal Market`,
    description: `Live prediction markets categorized under ${parsed.label}.`,
    path: `/categories/${parsed.slug}`,
  });
}

export async function CategoryMarkets({ slug }: { slug: string }) {
  const markets = await fetchFeaturedMarkets(MAX_CATEGORY_MARKETS, { category: slug });
  if (markets.length === 0) {
    return (
      <div className="rounded-3xl border border-white/10 bg-slate-900/40 p-10 text-center text-slate-400">
        No markets are currently listed under this category. Check back soon or try another filter.
      </div>
    );
  }
  return <MarketGrid markets={markets} />;
}

export default async function CategoryPage({ params }: CategoryPageProps) {
  const { category } = await params;
  const parsed = parseCategorySlug(category);
  if (!parsed) {
    notFound();
  }
  const label = parsed!.label;
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-white">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Category</p>
        <h1 className="text-3xl font-semibold">{label}</h1>
        <p className="text-slate-400">
          Live markets classified under “{label}”. Use the search bar or quick tags to pivot to other narratives.
        </p>
      </div>
      <Suspense fallback={<MarketGridSkeleton />}>
        <CategoryMarkets slug={parsed!.slug} />
      </Suspense>
    </div>
  );
}
