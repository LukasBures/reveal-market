import type { Metadata } from "next";
import { Suspense } from "react";
import { MarketFilters } from "@/components/markets/MarketFilters";
import { FeaturedMarketsSection, FeaturedMarketsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { buildMetadata } from "@/lib/seo";
import { fetchInvestorKpis, fetchMarketStatsBreakdown } from "@/lib/api";
import { Hero } from "@/components/marketing/Hero";
import { formatNumber } from "@/lib/formatters";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market | Private Prediction Markets",
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
  const [stats, kpis] = await Promise.all([fetchMarketStatsBreakdown(), fetchInvestorKpis()]);
  const liveMarkets = stats.find((stat) => stat.status === "live")?.count ?? 0;
  const finalizedMarkets = stats.find((stat) => stat.status === "finalized")?.count ?? 0;
  const totalMarkets = stats.find((stat) => stat.status === "total")?.count ?? liveMarkets + finalizedMarkets;
  const callouts = [
    { label: "Live markets", value: liveMarkets > 0 ? formatNumber(liveMarkets) : "—" },
    { label: "Markets settled", value: finalizedMarkets > 0 ? formatNumber(finalizedMarkets) : "—" },
    { label: "Total markets tracked", value: totalMarkets > 0 ? formatNumber(totalMarkets) : "—" },
    { label: "Access", value: "Invite only" },
  ];
  const storyHighlights = [
    {
      title: "Trade without broadcasting",
      description: "Entries stay hidden while the market runs, so your calls don't get chased or copied.",
    },
    {
      title: "See the story at settle",
      description: "When outcomes land, everyone gets a clean recap of what paid out and why.",
    },
    {
      title: "Humans in the loop",
      description: "The ops desk flags pauses, rule tweaks, and claims so you're never guessing what changed.",
    },
    {
      title: "Built for curiosity",
      description: "Markets cover sports, politics, macro catalysts, and the cultural moments investors debate.",
    },
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
