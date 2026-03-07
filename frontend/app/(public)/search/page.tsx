import type { Metadata } from "next";

import { SearchEventsClient } from "@/components/markets/SearchMarketsClient";
import { fetchFeaturedEvents } from "@/lib/api";
import { buildMetadata } from "@/lib/seo";
import { DEFAULT_PAGE_SIZE } from "@/components/markets/constants";
import { parseCategorySlug } from "@/lib/slugs";

export const revalidate = 60;
export const dynamic = "force-static";

export const metadata: Metadata = buildMetadata({
  title: "Search Prediction Events and Categories | Reveal Market",
  description:
    "Browse private prediction events across categories and statuses, then verify outcomes with settlement receipts and claim payouts when markets resolve.",
  path: "/search",
  keywords: [
    "private prediction events",
    "event search",
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
    ? (await fetchFeaturedEvents(DEFAULT_PAGE_SIZE, {
        searchQuery: effectiveQuery || undefined,
        status: initialStatus,
        category: initialCategory ?? undefined,
        orderBy: "volume",
      })).data
    : [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-12 text-white pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
      <div className="space-y-3">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Events</p>
        <h1 className="text-3xl font-semibold text-white sm:text-4xl">Search private prediction events</h1>
        <p className="text-base text-slate-300 sm:text-lg">
          Browse live and settled events. Fixed tickets; entries stay private until settlement and receipts publish when
          outcomes post.
        </p>
        <p className="text-sm text-white/70">
          Type at least 2 characters to search. Filters apply to live and resolved markets.
        </p>
      </div>
      <div className="mt-8">
        <SearchEventsClient
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
