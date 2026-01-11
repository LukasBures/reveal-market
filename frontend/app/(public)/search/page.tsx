import type { Metadata } from "next";

import { SearchMarketsClient } from "@/components/markets/SearchMarketsClient";
import { fetchFeaturedMarkets } from "@/lib/api";
import { buildMetadata } from "@/lib/seo";
import { DEFAULT_PAGE_SIZE } from "@/components/markets/constants";
import { parseCategorySlug } from "@/lib/slugs";

export const dynamic = "force-dynamic";

export const metadata: Metadata = buildMetadata({
  title: "Search Markets | Reveal Market",
  description:
    "Browse live and settled private prediction markets with fixed ticket size. Search by category or status and claim after settlement.",
  path: "/search",
  keywords: [
    "private prediction markets",
    "market search",
    "fixed ticket size",
    "claim after settlement",
    "settlement receipts",
  ],
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
    <div className="mx-auto max-w-7xl px-4 py-16 text-white pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <div className="space-y-3">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Markets</p>
        <h1 className="text-4xl font-semibold text-white">Search private prediction markets</h1>
        <p className="text-lg text-slate-300">
          Browse live and settled markets. Fixed tickets; entries stay private until settlement and receipts publish when
          outcomes post.
        </p>
        <p className="text-sm text-white/70">
          Tip: type at least two characters. Filters apply to private markets with fixed ticket size and claim after
          settlement.
        </p>
      </div>
      <div className="mt-8">
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
