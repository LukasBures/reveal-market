import type { Metadata } from "next";
import { Suspense } from "react";

import { FeaturedEventsSection, FeaturedEventsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { buildMetadata } from "@/lib/seo";
import { parseCategorySlug } from "@/lib/slugs";

export const metadata: Metadata = buildMetadata({
  title: "Private Prediction Markets With Verified Settlements",
  description:
    "Keep order flow private while markets are live. Reveal Market publishes settlement receipts so you can verify outcomes, confirm payouts, and claim securely.",
  path: "/",
  keywords: [
    "private prediction markets",
    "fixed ticket size",
    "signed quotes",
    "settlement receipts",
    "claim payouts",
  ],
});

export const revalidate = 60;
export const dynamic = "force-dynamic";

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: PageProps) {
  // Avoid blocking the home render on a health probe.
  const resolvedParams = (await searchParams) ?? {};
  const rawSearchQuery = typeof resolvedParams.q === "string" ? resolvedParams.q : undefined;
  const normalizedSearch = rawSearchQuery?.trim() ?? "";
  const hasShortSearch = normalizedSearch.length > 0 && normalizedSearch.length < 2;
  const effectiveSearchQuery = hasShortSearch ? undefined : normalizedSearch || undefined;
  const searchNotice = hasShortSearch ? "Enter at least two characters to search events." : undefined;
  const rawCategoryParam = typeof resolvedParams.category === "string" ? resolvedParams.category : undefined;
  const parsedCategory = rawCategoryParam ? parseCategorySlug(rawCategoryParam) : null;
  const rawSortParam = typeof resolvedParams.sort === "string" ? resolvedParams.sort : undefined;
  const categoryFilter = (() => {
    if (!parsedCategory) return undefined;
    if (parsedCategory.slug === "ai-tech") return "AI & Tech";
    if (parsedCategory.slug === "elections") return "Politics";
    return parsedCategory.label;
  })();
  const sortBy = (() => {
    if (rawSortParam === "newest") return "recent";
    if (rawSortParam === "trending") return "popularity";
    return "totalVolume";
  })();
  return (
    <div className="mx-auto max-w-7xl px-4 pt-4 pb-16 text-white pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <h1 className="sr-only">Reveal Market private prediction markets</h1>
      <div>
        <Suspense fallback={<FeaturedEventsSkeleton />}>
          <FeaturedEventsSection
            searchQuery={effectiveSearchQuery}
            emptyNotice={searchNotice}
            categoryFilter={categoryFilter}
            sortBy={sortBy}
            status={effectiveSearchQuery ? "any" : "active"}
            onlyActive={!effectiveSearchQuery}
            closesWithinHours={24}
          />
        </Suspense>
      </div>
    </div>
  );
}
