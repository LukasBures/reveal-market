import type { Metadata } from "next";
import { Suspense } from "react";
import { FeaturedMarketsSection, FeaturedMarketsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { buildMetadata } from "@/lib/seo";
import { fetchHealthSnapshot, fetchInvestorKpis, fetchMarketStatsBreakdown } from "@/lib/api";
import { Hero } from "@/components/marketing/Hero";
import { formatNumber } from "@/lib/formatters";

export const metadata: Metadata = buildMetadata({
  title: "Private Prediction Markets",
  description:
    "Invite-only prediction markets where entries stay private until results post, with clear receipts when they settle.",
  path: "/",
  keywords: [
    "private prediction markets",
    "invite only markets",
    "sports and politics markets",
    "macro event forecasts",
    "hidden orderflow",
    "Reveal Market platform",
  ],
});

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: PageProps) {
  const [stats, health] = await Promise.all([fetchMarketStatsBreakdown(), fetchHealthSnapshot()]);
  const kpis = await fetchInvestorKpis(stats, health);
  const liveMarkets = stats.find((stat) => stat.status === "live")?.count ?? 0;
  const endedMarkets = stats.find((stat) => stat.status === "finalized")?.count ?? 0;
  const callouts = [
    { label: "Live markets", value: formatNumber(liveMarkets) },
    { label: "Ended markets", value: formatNumber(endedMarkets) },
  ];
  const resolvedParams = (await searchParams) ?? {};
  const rawSearchQuery = typeof resolvedParams.q === "string" ? resolvedParams.q : undefined;
  const normalizedSearch = rawSearchQuery?.trim() ?? "";
  const hasShortSearch = normalizedSearch.length > 0 && normalizedSearch.length < 2;
  const effectiveSearchQuery = hasShortSearch ? undefined : normalizedSearch || undefined;
  const searchNotice = hasShortSearch ? "Enter at least two characters to search markets." : undefined;

  return (
    <div className="relative text-white">
      <Hero stats={callouts} />
      <div className="mx-auto flex max-w-7xl flex-col gap-10 px-4 pb-12">
        <Suspense fallback={<FeaturedMarketsSkeleton />}>
          <FeaturedMarketsSection searchQuery={effectiveSearchQuery} emptyNotice={searchNotice} />
        </Suspense>
      </div>
    </div>
  );
}
