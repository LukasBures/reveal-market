import type { Metadata } from "next";
import { cookies } from "next/headers";
import { Suspense } from "react";

import { LandingGate } from "@/components/landing/LandingGate";
import { Hero } from "@/components/marketing/Hero";
import { FeaturedMarketsSection, FeaturedMarketsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { fetchHealthSnapshot, fetchInvestorKpis, fetchMarketStatsBreakdown } from "@/lib/api";
import { formatNumber } from "@/lib/formatters";
import { buildMetadata } from "@/lib/seo";
import { LANDING_ACCESS_COOKIE_NAME, isLandingGateEnabled } from "@/lib/access-gate";

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

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: PageProps) {
  const gateEnabled = isLandingGateEnabled();
  let hasAccess = true;
  if (gateEnabled) {
    try {
      const cookieStore = await cookies();
      hasAccess = cookieStore.get(LANDING_ACCESS_COOKIE_NAME)?.value === "granted";
    } catch {
      hasAccess = true;
    }
  }
  if (gateEnabled && !hasAccess) {
    return <LandingGate />;
  }

  const [stats, health] = await Promise.all([fetchMarketStatsBreakdown(), fetchHealthSnapshot()]);
  const kpis = await fetchInvestorKpis(stats, health);
  const liveMarkets = stats.find((stat) => stat.status === "live")?.count ?? 0;
  const endedMarkets =
    stats.find((stat) => stat.status === "ended")?.count ??
    stats.find((stat) => stat.status === "finalized")?.count ??
    0;
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
    <div className="mx-auto max-w-7xl px-4 py-16 text-white pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <Hero stats={callouts} />
      <div className="mt-10">
        <Suspense fallback={<FeaturedMarketsSkeleton />}>
          <FeaturedMarketsSection searchQuery={effectiveSearchQuery} emptyNotice={searchNotice} />
        </Suspense>
      </div>
    </div>
  );
}
