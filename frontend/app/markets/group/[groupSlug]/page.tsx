import type { Metadata } from "next";
import { notFound } from "next/navigation";
import dynamic from "next/dynamic";
import { fetchGroupedMarkets } from "@/lib/api";
import type { MarketDetail } from "@/lib/api-types";
import { buildMetadata } from "@/lib/seo";
import { GroupedMarketSelector } from "@/components/markets/GroupedMarketSelector";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import { MarketLiveStatusBar } from "@/components/markets/MarketLiveStatusBar";
import { MarketDetailOutcomes } from "@/components/markets/MarketDetailOutcomes";
import { MarketDetailChart } from "@/components/markets/MarketDetailChart";
import { MarketAnalyticsPanel } from "@/components/markets/MarketAnalyticsPanel";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";
import { MarketLivePanels } from "@/components/markets/MarketLivePanels";
import { fetchMarketActivity } from "@/lib/streamer-data";

const MarketDetailMetadataPanel = dynamic(
  () =>
    import("@/components/markets/MarketDetailMetadata").then((mod) => ({
      default: mod.MarketDetailMetadata,
    })),
  {
    loading: () => (
      <section className="h-64 animate-pulse rounded-3xl border border-white/10 bg-slate-900/40 p-6" aria-label="Loading market metadata" />
    ),
  },
);

const MarketDetailSidebarPanel = dynamic(
  () =>
    import("@/components/markets/MarketDetailSidebar").then((mod) => ({
      default: mod.MarketDetailSidebar,
    })),
  {
    loading: () => (
      <aside
        className="min-h-[320px] animate-pulse rounded-3xl border border-white/10 bg-slate-900/70 p-6"
        aria-label="Loading market sidebar"
      />
    ),
  },
);

type GroupParams = {
  groupSlug: string;
};

type GroupPageProps = {
  params: Promise<GroupParams>;
};

const selectMarketCopy = (market: MarketDetail): string => {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const normalized = (value?: string | null) => (typeof value === "string" ? value.trim() : "");
  return (
    normalized(market.description) ||
    normalized(extraData?.gamma?.description) ||
    normalized(extraData?.gamma?.question) ||
    "This grouped market aggregates related thresholds."
  );
};

const resolveMarketImage = (market: MarketDetail): string | undefined => {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const gamma = extraData?.gamma as Record<string, any> | undefined;
  const candidates = [market.imageUrl, extraData?.image_url, extraData?.imageUrl, gamma?.image_url, gamma?.imageUrl, gamma?.cover_image, gamma?.coverImage];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return undefined;
};

export async function generateMetadata({ params }: GroupPageProps): Promise<Metadata> {
  const { groupSlug } = await params;
  const grouped = await fetchGroupedMarkets(groupSlug);
  const market = grouped?.markets?.[0];
  const title = market ? `${market.title} | Reveal Market` : `Markets group ${groupSlug} | Reveal Market`;
  const description = market ? selectMarketCopy(market).slice(0, 140) : "Aggregated markets bundle.";
  return buildMetadata({
    title,
    description,
    path: `/markets/group/${encodeURIComponent(groupSlug)}`,
  });
}

export default async function GroupedMarketPage({ params }: GroupPageProps) {
  const { groupSlug } = await params;
  const grouped = await fetchGroupedMarkets(groupSlug);
  if (!grouped || !grouped.markets.length) {
    notFound();
  }
  const market = grouped.markets[0];
  const coverImage = resolveMarketImage(market);
  const tokenIds = Array.isArray(market.clobTokenIds)
    ? market.clobTokenIds.map((t: string | number) => String(t))
    : [];
  const activity = market.conditionId ? await fetchMarketActivity(market.conditionId, { limit: 12 }) : [];

  return (
    <>
      <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-10">
          <GroupedMarketSelector groupSlug={grouped.groupSlug} siblings={market.siblings ?? []} activeEventId={market.eventId} />
          <MarketDetailHeader market={market} coverImage={coverImage} />
          <MarketLiveStatusBar marketId={market.eventId} tokenIds={tokenIds} />
          <div className="grid gap-6 lg:grid-cols-[1.7fr,1fr]">
            <div className="space-y-6">
              <MarketDetailOutcomes market={market} />
              <MarketDetailChart marketId={market.eventId} tokenIds={tokenIds} outcomes={Array.isArray(market.outcomes) ? market.outcomes : []} />
              <MarketAnalyticsPanel market={market} />
              <section className="rounded-3xl border border-slate-800 bg-slate-950 p-6 text-sm text-slate-300">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Market context</p>
                    <p className="mt-3">{selectMarketCopy(market)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.25em] text-slate-400">
                    {market.category && (
                      <span className="rounded-full bg-white/5 px-3 py-1 text-white/80">{market.category}</span>
                    )}
                    {market.status && (
                      <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-emerald-100">
                        {market.status.toUpperCase()}
                      </span>
                    )}
                  </div>
                </div>
              </section>
              <MarketDetailMetadataPanel market={market} />
            </div>
            <div className="space-y-4">
              <StakeQuoteCard
                marketAddress={market.marketAddress}
                marketId={market.eventId}
                outcomes={market.outcomes ?? []}
                outcomePrices={market.outcomePrices ?? []}
                initialOutcomeId={0}
              />
              <MarketLivePanels marketId={market.eventId} tokenIds={tokenIds} />
              <MarketDetailSidebarPanel market={market} />
            </div>
          </div>
        </div>
      </div>
      {market && (
        <script
          type="application/ld+json"
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: JSON.stringify({ "@context": "https://schema.org", "@type": "Collection", name: market.title }) }}
        />
      )}
    </>
  );
}
