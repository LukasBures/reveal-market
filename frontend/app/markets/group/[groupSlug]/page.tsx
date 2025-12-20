import type { Metadata } from "next";
import { notFound } from "next/navigation";
import dynamic from "next/dynamic";
import { fetchGroupedMarkets } from "@/lib/api";
import type { MarketDetail } from "@/lib/api-types";
import { buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { GroupedMarketSelector } from "@/components/markets/GroupedMarketSelector";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import { MarketLiveStatusBar } from "@/components/markets/MarketLiveStatusBar";
import { MarketDetailChart } from "@/components/markets/MarketDetailChart";
import { MarketAnalyticsPanel } from "@/components/markets/MarketAnalyticsPanel";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";
import { formatDateTime } from "@/lib/formatters";
import { resolvePriceStreamMarketId } from "@/lib/markets";
import { JsonLd } from "@/components/seo/JsonLd";

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

type GroupParams = {
  groupSlug: string;
};

type GroupPageProps = {
  params: Promise<GroupParams>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

const humanizeGroupSlug = (slug?: string | null): string | undefined => {
  if (!slug) return undefined;
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
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

const resolveTargetEventId = (searchParams: Record<string, string | string[] | undefined>): string | undefined => {
  const rawCandidate =
    searchParams.eventId ?? searchParams.event ?? searchParams.marketId ?? searchParams.market ?? undefined;
  const candidate = Array.isArray(rawCandidate) ? rawCandidate[0] : rawCandidate;
  const trimmed = typeof candidate === "string" ? candidate.trim() : "";
  return trimmed || undefined;
};

const selectActiveMarket = (markets: MarketDetail[], targetEventId?: string): MarketDetail => {
  if (targetEventId) {
    const normalizedTarget = targetEventId.trim();
    const match = markets.find((item) => (item.eventId ?? "").toString().trim() === normalizedTarget);
    if (match) return match;
  }
  return markets[0];
};

export async function generateMetadata({ params, searchParams }: GroupPageProps): Promise<Metadata> {
  const { groupSlug } = await params;
  const resolvedSearchParams = (await searchParams) ?? {};
  const targetEventId = resolveTargetEventId(resolvedSearchParams);
  const grouped = await fetchGroupedMarkets(groupSlug);
  const market = grouped?.markets?.length ? selectActiveMarket(grouped.markets, targetEventId) : undefined;
  const title = market ? `${market.title} | Reveal Market` : `Markets group ${groupSlug} | Reveal Market`;
  const description = market ? selectMarketCopy(market).slice(0, 140) : "Aggregated markets bundle.";
  const image = market ? resolveMarketImage(market) : undefined;
  return buildMetadata({
    title,
    description,
    path: `/markets/group/${encodeURIComponent(groupSlug)}`,
    image,
  });
}

export default async function GroupedMarketPage({ params, searchParams }: GroupPageProps) {
  const { groupSlug } = await params;
  const resolvedSearchParams = (await searchParams) ?? {};
  const targetEventId = resolveTargetEventId(resolvedSearchParams);
  const grouped = await fetchGroupedMarkets(groupSlug);
  if (!grouped || !grouped.markets.length) {
    notFound();
  }
  const market = selectActiveMarket(grouped.markets, targetEventId);
  const coverImage = resolveMarketImage(market);
  const tokenIds = Array.isArray(market.clobTokenIds)
    ? market.clobTokenIds.map((t: string | number) => String(t))
    : [];
  const priceStreamMarketId = resolvePriceStreamMarketId(market, market.eventId);
  const resolverSource =
    market.resolutionSource ??
    (market.extraData as any)?.resolution_source ??
    (market.extraData as any)?.gamma?.resolution_source ??
    null;
  const resolverLabel = typeof resolverSource === "string" && resolverSource.trim() ? resolverSource.trim() : "Not provided";
  const commitDeadline = market.commitDeadline ?? market.closesAt ?? market.ordersOpenedAt ?? null;
  const selectorSiblings =
    market.siblings?.length && market.siblings.every((s) => s.eventId)
      ? market.siblings
      : grouped.markets.map((item) => ({
          eventId: item.eventId ?? "",
          title: item.title,
          status: item.status,
          groupItemTitle: item.groupItemTitle ?? null,
          groupItemThreshold: item.groupItemThreshold ?? null,
          groupPosition: item.groupPosition ?? null,
          outcomePrices: item.outcomePrices ?? [],
          volume: item.volume ?? 0,
          volume24hUsd: item.volume24hUsd ?? null,
          liquidityUsd: item.liquidityUsd ?? null,
          commitDeadline: item.commitDeadline ?? item.closesAt ?? item.ordersOpenedAt ?? null,
          startsAt: item.startsAt ?? null,
          closesAt: item.closesAt ?? null,
        }));
  const marketPath = market.eventId
    ? `/markets/group/${groupSlug}?eventId=${encodeURIComponent(market.eventId)}`
    : `/markets/group/${groupSlug}`;
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Markets", path: "/markets" },
    { name: market.title, path: marketPath },
  ]);
  return (
    <>
      <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-10">
          <MarketDetailHeader market={market} coverImage={coverImage} />
          <MarketLiveStatusBar marketId={priceStreamMarketId} tokenIds={tokenIds} />
          <div className="grid gap-6 lg:grid-cols-[1.7fr,1fr]">
            <div className="space-y-6">
              <GroupedMarketSelector
                groupSlug={grouped.groupSlug}
                siblings={selectorSiblings}
                activeEventId={market.eventId}
                linkToGroupPage
                labelOverride="Grouped market"
                titleOverride={humanizeGroupSlug(grouped.groupSlug) ?? market.title}
                subtitleOverride="Choose a sub-market within this event bundle."
                forceShow
              />
              <MarketDetailChart
                marketId={priceStreamMarketId}
                tokenIds={tokenIds}
                outcomes={Array.isArray(market.outcomes) ? market.outcomes : []}
                outcomePrices={market.outcomePrices ?? []}
              />
              <section className="rounded-3xl border border-slate-800 bg-slate-950 p-6 text-sm text-slate-300">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Market context</p>
                    <div className="mt-3 space-y-3 text-slate-200">
                      <p className="text-sm font-semibold text-white">Resolution criteria</p>
                      <div className="whitespace-pre-line text-sm leading-relaxed text-slate-200">{selectMarketCopy(market)}</div>
                      <ul className="mt-2 space-y-1 text-xs text-slate-400">
                        <li>Resolver source: {resolverLabel}</li>
                        <li>Commit deadline: {commitDeadline ? formatDateTime(commitDeadline) : "TBA"}</li>
                        <li>Reveal deadline: {market.revealDeadline ? formatDateTime(market.revealDeadline) : "TBA"}</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </section>
              <MarketAnalyticsPanel market={market} />
              <MarketDetailMetadataPanel market={market} />
            </div>
            <div className="space-y-4">
              <StakeQuoteCard
                marketAddress={market.marketAddress}
                marketId={market.eventId}
                outcomes={market.outcomes ?? []}
                outcomePrices={market.outcomePrices ?? []}
                initialOutcomeId={0}
                marketTitle={market.title}
                marketStatus={market.status}
                isResolved={market.resolution?.resolved ?? null}
              />
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
      <JsonLd data={breadcrumbs} id="grouped-market-breadcrumbs" />
    </>
  );
}
