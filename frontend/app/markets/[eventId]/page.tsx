import type { Metadata } from "next";
import dynamic from "next/dynamic";
import { notFound } from "next/navigation";
import { cache } from "react";
import { fetchFeaturedMarkets, fetchMarketByEventId } from "@/lib/api";
import type { MarketDetail } from "@/lib/api-types";
import { absoluteUrl, buildMetadata } from "@/lib/seo";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import { MarketDetailOutcomes } from "@/components/markets/MarketDetailOutcomes";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";
import { MarketLivePanels } from "@/components/markets/MarketLivePanels";
import { MarketDetailChart } from "@/components/markets/MarketDetailChart";
import { MarketLiveStatusBar } from "@/components/markets/MarketLiveStatusBar";
import { MarketAnalyticsPanel } from "@/components/markets/MarketAnalyticsPanel";
import { MarketActivityPanel } from "@/components/markets/MarketActivityPanel";
import { fetchMarketActivity } from "@/lib/streamer-data";
import { GroupedMarketSelector } from "@/components/markets/GroupedMarketSelector";

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

type MarketDetailParams = {
  eventId: string;
};

type MarketDetailPageProps = {
  params: Promise<MarketDetailParams>;
};

const MARKET_CONTEXT_FALLBACK =
  "This market mirrors Reveal Market’s commit/reveal rails. Settlement proofs are recorded on-chain and mirrored in the backend resolution ledger.";
const MARKET_DESCRIPTION_MAX_LENGTH = 320;
const DEFAULT_EVENT_STATUS = "https://schema.org/EventScheduled";
const SCHEMA_EVENT_STATUS_MAP: Record<string, string> = {
  commit: DEFAULT_EVENT_STATUS,
  open: DEFAULT_EVENT_STATUS,
  locked: "https://schema.org/EventPostponed",
  disputed: "https://schema.org/EventPostponed",
  settled: "https://schema.org/EventCompleted",
  resolved: "https://schema.org/EventCompleted",
  cancelled: "https://schema.org/EventCancelled",
  canceled: "https://schema.org/EventCancelled",
  voided: "https://schema.org/EventCancelled",
};

const loadMarket = cache(async (eventId: string) => fetchMarketByEventId(eventId));

const buildMarketPath = (eventId: string): string => `/markets/${encodeURIComponent(eventId)}`;

const selectMarketCopy = (market: MarketDetail): string => {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const normalized = (value?: string | null) => (typeof value === "string" ? value.trim() : "");
  return (
    normalized(extraData?.context) ||
    normalized(market.description) ||
    normalized(extraData?.gamma?.description) ||
    normalized(extraData?.gamma?.question) ||
    MARKET_CONTEXT_FALLBACK
  );
};

const clampDescription = (copy: string, maxLength = MARKET_DESCRIPTION_MAX_LENGTH): string =>
  copy.length > maxLength ? `${copy.slice(0, maxLength - 1).trim()}…` : copy;

const resolveMarketImage = (market: MarketDetail): string | undefined => {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const gamma = extraData?.gamma as Record<string, any> | undefined;
  const candidates = [
    market.imageUrl,
    extraData?.image_url,
    extraData?.imageUrl,
    gamma?.image_url,
    gamma?.imageUrl,
    gamma?.cover_image,
    gamma?.coverImage,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return undefined;
};

const getCanonicalEventId = (market: MarketDetail, fallback: string): string =>
  market.eventId && market.eventId !== "unknown" ? market.eventId : fallback;

const extractMarketKeywords = (market: MarketDetail): string[] => {
  const source = [
    market.category,
    market.status,
    ...(Array.isArray(market.tags) ? market.tags : []),
  ];
  const seen = new Set<string>();
  const keywords: string[] = [];
  source.forEach((value) => {
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed && !seen.has(trimmed.toLowerCase())) {
        seen.add(trimmed.toLowerCase());
        keywords.push(trimmed);
      }
    }
  });
  return keywords;
};

const mapMarketStatusToSchema = (status?: string): string => {
  if (!status) {
    return DEFAULT_EVENT_STATUS;
  }
  return SCHEMA_EVENT_STATUS_MAP[status.toLowerCase()] ?? DEFAULT_EVENT_STATUS;
};

const buildMarketStructuredData = (
  market: MarketDetail,
  description: string,
  canonicalPath: string,
): Record<string, any> => {
  const url = absoluteUrl(canonicalPath);
  const keywords = extractMarketKeywords(market);
  const structuredData: Record<string, any> = {
    "@context": "https://schema.org",
    "@type": "Event",
    name: market.title,
    description,
    eventStatus: mapMarketStatusToSchema(market.status),
    eventAttendanceMode: "https://schema.org/OnlineEventAttendanceMode",
    startDate: market.commitDeadline ?? market.createdAt ?? undefined,
    endDate: market.revealDeadline ?? market.updatedAt ?? undefined,
    url,
    image: [absoluteUrl(resolveMarketImage(market) ?? "/opengraph-image")],
    organizer: {
      "@type": "Organization",
      name: "Reveal Market",
      url: absoluteUrl("/"),
    },
    location: {
      "@type": "VirtualLocation",
      url,
    },
  };
  if (keywords.length > 0) {
    structuredData.keywords = keywords.join(", ");
  }
  if (typeof market.liquidityUsd === "number" && Number.isFinite(market.liquidityUsd)) {
    structuredData.offers = {
      "@type": "Offer",
      priceCurrency: "USD",
      price: market.liquidityUsd.toString(),
      url,
      availability: "https://schema.org/InStock",
    };
  }
  return structuredData;
};

export const dynamicParams = true;

export type GenerateStaticParams = () => Promise<MarketDetailParams[]>;

export const generateStaticParams: GenerateStaticParams = async () => {
  try {
    const markets = await fetchFeaturedMarkets(12);
    return markets
      .map((market) => market.eventId)
      .filter((eventId): eventId is string => Boolean(eventId && eventId !== "unknown"))
      .map((eventId) => ({ eventId }));
  } catch (error) {
    console.error("Unable to prebuild market detail params", error);
    return [];
  }
};

export async function generateMetadata({ params }: MarketDetailPageProps): Promise<Metadata> {
  const { eventId } = await params;
  const fallbackPath = buildMarketPath(eventId);
  const market = await loadMarket(eventId);
  if (!market) {
    return buildMetadata({
      title: "Market unavailable | Reveal Market",
      description: "This market could not be located or is no longer visible.",
      path: fallbackPath,
      robots: { index: false, follow: false },
    });
  }
  const canonicalEventId = getCanonicalEventId(market, eventId);
  const canonicalPath = buildMarketPath(canonicalEventId);
  const description = clampDescription(selectMarketCopy(market));
  return buildMetadata({
    title: `${market.title} | Reveal Market`,
    description,
    path: canonicalPath,
    keywords: extractMarketKeywords(market),
    image: resolveMarketImage(market),
    type: "article",
  });
}

export default async function MarketDetailPage({ params }: MarketDetailPageProps) {
  const { eventId } = await params;
  const market = await loadMarket(eventId);
  if (!market) {
    notFound();
  }
  const canonicalEventId = getCanonicalEventId(market, eventId);
  const canonicalPath = buildMarketPath(canonicalEventId);
  const contextCopy = selectMarketCopy(market);
  const structuredData = buildMarketStructuredData(market, contextCopy, canonicalPath);
  const coverImage = resolveMarketImage(market);
  const tokenIds = Array.isArray(market.clobTokenIds) ? market.clobTokenIds.map((t) => String(t)) : [];
  const siblings = Array.isArray(market.siblings) ? market.siblings : [];
  const isGrouped = Boolean(market.groupSlug && siblings.length > 1);
  const activity = market.conditionId ? await fetchMarketActivity(market.conditionId, { limit: 12 }) : [];

  return (
    <>
      <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-10">
          {isGrouped && market.groupSlug && (
            <GroupedMarketSelector groupSlug={market.groupSlug} siblings={siblings} activeEventId={canonicalEventId} />
          )}
          <MarketDetailHeader market={market} coverImage={coverImage} />
          <MarketLiveStatusBar marketId={canonicalEventId} tokenIds={tokenIds} />
          <div className="grid gap-6 lg:grid-cols-[1.7fr,1fr]">
            <div className="space-y-6">
              <MarketDetailOutcomes market={market} />
              <MarketDetailChart
                marketId={canonicalEventId}
                tokenIds={tokenIds}
                outcomes={Array.isArray(market.outcomes) ? market.outcomes : []}
              />
              <MarketAnalyticsPanel market={market} />
              <section className="rounded-3xl border border-slate-800 bg-slate-950 p-6 text-sm text-slate-300">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Market context</p>
                    <p className="mt-3">{contextCopy}</p>
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
                marketId={canonicalEventId}
                outcomes={market.outcomes ?? []}
                outcomePrices={market.outcomePrices ?? []}
                initialOutcomeId={0}
              />
              <MarketLivePanels marketId={canonicalEventId} tokenIds={tokenIds} />
              <MarketDetailSidebarPanel market={market} />
            </div>
          </div>
        </div>
      </div>
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />
    </>
  );
}
