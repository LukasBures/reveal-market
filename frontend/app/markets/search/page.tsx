import type { Metadata } from "next";

import { SearchMarketsClient } from "@/components/markets/SearchMarketsClient";
import { fetchFeaturedMarkets } from "@/lib/api";
import { buildMetadata } from "@/lib/seo";
import { DEFAULT_PAGE_SIZE } from "@/components/markets/constants";

export const metadata: Metadata = buildMetadata({
  title: "Search Markets | Reveal Market",
  description: "Search live and finalized markets with cached results and lazy loading.",
  path: "/markets/search",
  keywords: ["market search", "reveal market search", "prediction market search"],
  robots: { index: false, follow: true },
});

type PageProps = {
  searchParams?: Promise<{ q?: string | string[] }>;
};

export default async function MarketsSearchPage({ searchParams }: PageProps) {
  const resolvedParams = (await searchParams) ?? {};
  const rawQuery = Array.isArray(resolvedParams.q) ? resolvedParams.q[0] : resolvedParams.q ?? "";
  const initialQuery = (rawQuery ?? "").trim();
  const initialResults =
    initialQuery.length >= 2
      ? await fetchFeaturedMarkets(DEFAULT_PAGE_SIZE, { searchQuery: initialQuery, status: "any", orderBy: "volume" })
      : [];

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-950 to-black px-4 py-10 text-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <SearchMarketsClient
          initialQuery={initialQuery}
          initialResults={initialResults}
          pageSize={DEFAULT_PAGE_SIZE}
        />
      </div>
    </div>
  );
}
