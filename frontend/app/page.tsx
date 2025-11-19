import type { Metadata } from "next";
import { Suspense } from "react";
import { MarketFilters } from "@/components/markets/MarketFilters";
import { FeaturedMarketsSection, FeaturedMarketsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { buildMetadata } from "@/lib/seo";
import { fetchInvestorKpis, fetchMarketStatsBreakdown } from "@/lib/api";
import { Hero } from "@/components/marketing/Hero";
import { formatNumber } from "@/lib/formatters";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market | Live Prediction Markets",
  description:
    "Browse institutional-grade prediction markets powered by Reveal Market’s zk-settlement stack.",
  path: "/",
  keywords: [
    "institutional prediction markets",
    "zero knowledge settlement",
    "onchain derivatives trading",
    "crypto event forecasting",
    "sports and politics odds",
    "Base chain markets",
    "decentralized risk exchange",
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
    { label: "Markets live", value: liveMarkets > 0 ? formatNumber(liveMarkets) : "—" },
    { label: "Markets finalized", value: finalizedMarkets > 0 ? formatNumber(finalizedMarkets) : "—" },
    { label: "Total markets tracked", value: totalMarkets > 0 ? formatNumber(totalMarkets) : "—" },
    { label: "Audit-ready proofs", value: "Groth16" },
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
        <section className="glass-panel p-4 sm:p-6">
          <MarketFilters
            initialSearch={rawSearchQuery}
            liveMarketsCount={liveMarkets}
            finalizedMarketsCount={finalizedMarkets}
            totalMarketsCount={totalMarkets}
          />
        </section>
        <Suspense fallback={<FeaturedMarketsSkeleton />}>
          <FeaturedMarketsSection searchQuery={effectiveSearchQuery} emptyNotice={searchNotice} />
        </Suspense>
        <section className="grid gap-4 rounded-[32px] border border-white/10 bg-black/40 p-6 text-slate-200 lg:grid-cols-3">
          <p className="col-span-full text-sm text-white/70">
            Markets below stream directly from our sealed commit rails. Browse categories, filter by narrative, or tap into the docs for deeper diligence.
          </p>
        </section>
      </div>
    </div>
  );
}
