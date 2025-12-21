import type { Metadata } from "next";

import { SearchMarketsClient } from "@/components/markets/SearchMarketsClient";
import { fetchFeaturedMarkets } from "@/lib/api";
import { buildMetadata } from "@/lib/seo";
import { DEFAULT_PAGE_SIZE } from "@/components/markets/constants";
import { parseCategorySlug } from "@/lib/slugs";

export const metadata: Metadata = buildMetadata({
  title: "Search Markets | Reveal Market",
  description: "Search live and finalized markets with cached results and lazy loading.",
  path: "/markets/search",
  keywords: ["market search", "reveal market search", "prediction market search"],
  robots: { index: false, follow: true },
});

type PageProps = {
  searchParams?: Promise<{
    q?: string | string[];
    category?: string | string[];
    status?: string | string[];
  }>;
};

export default async function MarketsSearchPage({ searchParams }: PageProps) {
  const resolvedParams = (await searchParams) ?? {};
  const rawQuery = Array.isArray(resolvedParams.q) ? resolvedParams.q[0] : resolvedParams.q ?? "";
  const rawCategory = Array.isArray(resolvedParams.category)
    ? resolvedParams.category[0]
    : resolvedParams.category ?? "";
  const rawStatus = Array.isArray(resolvedParams.status) ? resolvedParams.status[0] : resolvedParams.status ?? "";
  const initialQuery = (rawQuery ?? "").trim();
  const initialCategoryMatch = rawCategory ? parseCategorySlug(rawCategory) : null;
  const initialCategory = initialCategoryMatch?.label ?? null;
  const normalizedStatus = (() => {
    const status = (rawStatus ?? "").toString().trim().toLowerCase();
    const allowed = new Set(["any", "active", "locked", "settled", "cancelled"]);
    return allowed.has(status) ? status : null;
  })();
  const hasStatusParam = Boolean(normalizedStatus);
  const effectiveQuery = initialQuery.length >= 2 ? initialQuery : "";
  const fallbackStatus = effectiveQuery ? "any" : "active";
  const initialStatus = (normalizedStatus ?? fallbackStatus) as "any" | "active" | "locked" | "settled" | "cancelled";
  const shouldFetch = effectiveQuery.length >= 2 || Boolean(initialCategory) || hasStatusParam;
  const initialResults = shouldFetch
    ? await fetchFeaturedMarkets(DEFAULT_PAGE_SIZE, {
        searchQuery: effectiveQuery || undefined,
        status: initialStatus,
        category: initialCategory ?? undefined,
        orderBy: "volume",
      })
    : [];

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-950 to-black px-4 py-10 text-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <SearchMarketsClient
          initialQuery={initialQuery}
          initialCategory={initialCategory}
          initialStatus={initialStatus}
          initialResults={initialResults}
          pageSize={DEFAULT_PAGE_SIZE}
        />
      </div>
    </div>
  );
}
