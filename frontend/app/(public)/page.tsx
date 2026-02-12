import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";

import { FeaturedEventsSection, FeaturedEventsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { fetchHealthSnapshot } from "@/lib/api";
import { buildMetadata } from "@/lib/seo";
import { categorySlugFromLabel, parseCategorySlug } from "@/lib/slugs";
import type { Route } from "next";

export const metadata: Metadata = buildMetadata({
  title: "Private Prediction Markets",
  description:
    "Private prediction markets with fixed ticket size, signed quotes, and clear settlement receipts when outcomes post. Claim payouts once markets settle.",
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

const HERO_CATEGORY_FILTERS = ["All", "Crypto", "Finance", "Sports", "Geopolitics"];

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
  const hasActiveFilters = Boolean(parsedCategory) || Boolean(effectiveSearchQuery);

  return (
    <>
      <div className="sticky top-[72px] z-40 border-t border-white/5 bg-black/80 text-xs text-white/80 backdrop-blur">
        <div className="mx-auto w-full max-w-7xl px-4 py-2">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1">
              <div className="pointer-events-none absolute left-0 top-0 h-full w-10 bg-gradient-to-r from-black/80 to-transparent opacity-90" />
              <div className="pointer-events-none absolute right-0 top-0 h-full w-10 bg-gradient-to-l from-black/80 to-transparent opacity-90" />
              <div className="no-scrollbar flex snap-x snap-mandatory gap-2 overflow-x-auto pr-6">
                {HERO_CATEGORY_FILTERS.map((category) => {
                  const isAll = category.toLowerCase() === "all";
                  const slug =
                    categorySlugFromLabel(category) ?? category.toLowerCase().replace(/[^a-z0-9-]/g, "-");
                  const isActive = isAll ? !parsedCategory : parsedCategory?.slug === slug;
                  const params = new URLSearchParams();
                  if (effectiveSearchQuery) {
                    params.set("q", effectiveSearchQuery);
                  }
                  if (sortBy === "recent") {
                    params.set("sort", "newest");
                  } else if (sortBy === "popularity") {
                    params.set("sort", "trending");
                  }
                if (!isAll) {
                  params.set("category", slug);
                }
                const href = (isAll ? "/" : params.toString() ? `/?${params.toString()}` : "/") as Route;
                  return (
                    <Link
                      key={category}
                      href={href}
                      className={`relative snap-start rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] transition ${
                        isActive
                          ? "border-brand-400/80 bg-brand-400/20 text-white"
                          : "border-white/10 bg-white/5 text-white/80 hover:border-brand-400/60 hover:text-white hover:bg-white/10"
                      }`}
                    >
                      {null}
                      <span className="relative">{category}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {[
                { label: "Trending", value: "trending", active: sortBy === "popularity" },
                { label: "Volume", value: "volume", active: sortBy === "totalVolume" },
                { label: "Newest", value: "newest", active: sortBy === "recent" },
              ].map((pill) => {
                const params = new URLSearchParams();
                if (effectiveSearchQuery) {
                  params.set("q", effectiveSearchQuery);
                }
                if (parsedCategory) {
                  params.set("category", parsedCategory.slug);
                }
                if (pill.value !== "volume") {
                  params.set("sort", pill.value);
                }
                const href = (params.toString() ? `/?${params.toString()}` : "/") as Route;
                return (
                  <Link
                    key={pill.value}
                    href={href}
                    className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] transition ${
                      pill.active
                        ? "border-emerald-400/70 bg-emerald-400/20 text-emerald-100"
                        : "border-white/10 bg-white/5 text-white/70 hover:border-emerald-300/60 hover:text-white"
                    }`}
                  >
                    {pill.label}
                  </Link>
                );
              })}
              {hasActiveFilters ? (
                <Link
                  href="/"
                  className="rounded-full border border-red-400/60 bg-red-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] text-red-100 transition hover:border-red-300 hover:text-white hover:bg-red-500/20"
                >
                  Clear
                </Link>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      <div className="mx-auto max-w-7xl px-4 pt-4 pb-16 text-white pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <div>
          <Suspense fallback={<FeaturedEventsSkeleton />}>
            <FeaturedEventsSection
              searchQuery={effectiveSearchQuery}
              emptyNotice={searchNotice}
              categoryFilter={categoryFilter}
              sortBy={sortBy}
              status={effectiveSearchQuery ? "any" : "active"}
              onlyActive={!effectiveSearchQuery}
            />
          </Suspense>
        </div>
      </div>
    </>
  );
}
