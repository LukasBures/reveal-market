import type { Metadata } from "next";
import dynamicImport from "next/dynamic";
import { notFound } from "next/navigation";
import { cache } from "react";
import { fetchFeaturedEvents, fetchMarketByEventId } from "@/lib/api";
import type { MarketDetail } from "@/lib/api-types";
import { absoluteUrl, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";
import { MarketDetailChart } from "@/components/markets/MarketDetailChart";
import { MarketLiveStatusBar } from "@/components/markets/MarketLiveStatusBar";
import { MarketAnalyticsPanel } from "@/components/markets/MarketAnalyticsPanel";
import { GroupedMarketSelector } from "@/components/markets/GroupedMarketSelector";
import { getCommitDeadline, resolvePriceStreamMarketId } from "@/lib/markets";
import { formatDateTime } from "@/lib/formatters";
import { JsonLd } from "@/components/seo/JsonLd";

export const dynamic = "force-dynamic";

const humanizeGroupSlug = (slug?: string | null): string | undefined => {
  if (!slug) return undefined;
  return slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
};

const MarketDetailMetadataPanel = dynamicImport(
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

type MarketDetailParams = {
  eventId: string;
};

type MarketDetailPageProps = {
  params: Promise<MarketDetailParams>;
  searchParams?: Promise<{ outcome?: string }>;
};

const MARKET_CONTEXT_FALLBACK =
  "This market mirrors Reveal Event’s commit/reveal rails. Settlement proofs are recorded on-chain and mirrored in the backend resolution ledger.";
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

const loadEvent = cache(async (eventId: string) => fetchMarketByEventId(eventId));

const buildEventPath = (eventId: string): string => `/events/${encodeURIComponent(eventId)}`;

const selectEventCopy = (market: MarketDetail): string => {
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
  copy.length > maxLength ? `${copy.slice(0, maxLength - 1).trim()}...` : copy;

const resolveEventImage = (market: MarketDetail): string | undefined => {
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

const extractEventKeywords = (market: MarketDetail): string[] => {
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

const mapEventStatusToSchema = (status?: string): string => {
  if (!status) {
    return DEFAULT_EVENT_STATUS;
  }
  return SCHEMA_EVENT_STATUS_MAP[status.toLowerCase()] ?? DEFAULT_EVENT_STATUS;
};

const buildEventStructuredData = (
  market: MarketDetail,
  description: string,
  canonicalPath: string,
): Record<string, any> => {
  const url = absoluteUrl(canonicalPath);
  const keywords = extractEventKeywords(market);
  const commitDeadline = getCommitDeadline(market);
  const structuredData: Record<string, any> = {
    "@context": "https://schema.org",
    "@type": "Event",
    name: market.title,
    description,
    eventStatus: mapEventStatusToSchema(market.status),
    eventAttendanceMode: "https://schema.org/OnlineEventAttendanceMode",
    startDate: commitDeadline ?? market.createdAt ?? undefined,
    endDate: market.revealDeadline ?? market.updatedAt ?? undefined,
    url,
    image: [absoluteUrl(resolveEventImage(market) ?? "/opengraph-image")],
    organizer: {
      "@type": "Organization",
      name: "Reveal Event",
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
    const events = await fetchFeaturedEvents(12);
    return events
      .map((event) => event.eventId)
      .filter((eventId): eventId is string => Boolean(eventId && eventId !== "unknown"))
      .map((eventId) => ({ eventId }));
  } catch (error) {
    console.error("Unable to prebuild market detail params", error);
    return [];
  }
};

export async function generateMetadata({ params }: MarketDetailPageProps): Promise<Metadata> {
  const { eventId } = await params;
  const fallbackPath = buildEventPath(eventId);
  const market = await loadEvent(eventId);
  if (!market) {
    return buildMetadata({
      title: "Event unavailable | Reveal Event",
      description: "This market could not be located or is no longer visible.",
      path: fallbackPath,
      robots: { index: false, follow: false },
    });
  }
  const canonicalEventId = getCanonicalEventId(market, eventId);
  const canonicalPath = buildEventPath(canonicalEventId);
  const baseDescription = clampDescription(selectEventCopy(market));
  const description = `${baseDescription} Private prediction market with fixed ticket size and claims after settlement.`;
  return buildMetadata({
    title: `${market.title} | Reveal Event`,
    description,
    path: canonicalPath,
    keywords: extractEventKeywords(market),
    image: resolveEventImage(market),
    type: "article",
  });
}

export default async function MarketDetailPage({ params, searchParams }: MarketDetailPageProps) {
  const { eventId } = await params;
  const resolvedSearchParams = searchParams ? await searchParams : {};
  const requestedOutcome = resolvedSearchParams?.outcome ? Number(resolvedSearchParams.outcome) : null;
  const market = await loadEvent(eventId);
  if (!market) {
    notFound();
  }
  const canonicalEventId = getCanonicalEventId(market, eventId);
  const canonicalPath = buildEventPath(canonicalEventId);
  const contextCopy = selectEventCopy(market);
  const structuredData = buildEventStructuredData(market, contextCopy, canonicalPath);
  const coverImage = resolveEventImage(market);
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Events", path: "/search" },
    { name: market.title, path: canonicalPath },
  ]);
  const tokenIds = Array.isArray(market.clobTokenIds) ? market.clobTokenIds.map((t) => String(t)) : [];
  const priceStreamEventId = resolvePriceStreamMarketId(market, canonicalEventId);
  const siblings = Array.isArray(market.siblings) ? market.siblings : [];
  const resolverSource =
    market.resolutionSource ??
    (market.extraData as any)?.resolution_source ??
    (market.extraData as any)?.gamma?.resolution_source ??
    null;
  const resolverLabel = typeof resolverSource === "string" && resolverSource.trim() ? resolverSource.trim() : "Not provided";
  const commitDeadline = getCommitDeadline(market);
  const initialOutcomeId =
    typeof requestedOutcome === "number" && Number.isFinite(requestedOutcome) && requestedOutcome >= 0
      ? Math.min(requestedOutcome, (market.outcomes?.length ?? 1) - 1)
      : 0;
  const selectorSiblings =
    siblings.length > 0
      ? siblings
      : [
          {
            eventId: canonicalEventId,
            title: market.title,
            groupItemTitle: market.groupItemTitle,
            groupItemThreshold: market.groupItemThreshold,
            groupPosition: market.groupPosition,
            outcomePrices: market.outcomePrices ?? [],
            volume: market.volume ?? 0,
            volume24hUsd: market.volume24hUsd ?? null,
            liquidityUsd: market.liquidityUsd ?? null,
            commitDeadline: getCommitDeadline(market) ?? market.closesAt ?? market.commitDeadline ?? null,
            startsAt: market.startsAt ?? null,
            closesAt: market.closesAt ?? null,
          },
        ];

  return (
    <>
      <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-16 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
          <MarketDetailHeader market={market} coverImage={coverImage} />
          <MarketLiveStatusBar marketId={priceStreamEventId} tokenIds={tokenIds} />
          <div className="grid gap-6 lg:grid-cols-[1.7fr,1fr]">
            <div className="space-y-6">
              <GroupedMarketSelector
                groupSlug={market.groupSlug ?? canonicalEventId}
                siblings={selectorSiblings}
                activeEventId={canonicalEventId}
                labelOverride="Grouped market"
                titleOverride={humanizeGroupSlug(market.groupSlug) ?? market.title}
                subtitleOverride="Choose a sub-market within this event bundle."
                forceShow
              />
              <MarketDetailChart
                marketId={priceStreamEventId}
                tokenIds={tokenIds}
                outcomePrices={market.outcomePrices ?? []}
                outcomes={market.outcomes ?? []}
                initialOutcome={initialOutcomeId}
              />
              <section className="rounded-3xl border border-slate-800 bg-slate-950 p-6 text-sm text-slate-300">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Event context</p>
                    <div className="mt-3 space-y-3 text-slate-200">
                      <p className="text-sm font-semibold text-white">Resolution criteria</p>
                      <div className="whitespace-pre-line text-sm leading-relaxed text-slate-200">{contextCopy}</div>
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
              <div id="trade-panel">
                <StakeQuoteCard
                  marketAddress={market.marketAddress}
                  marketId={canonicalEventId}
                  outcomes={market.outcomes ?? []}
                  outcomePrices={market.outcomePrices ?? []}
                  initialOutcomeId={initialOutcomeId}
                  marketTitle={market.title}
                  marketStatus={market.status}
                  isResolved={market.resolution?.resolved ?? null}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
      <JsonLd data={breadcrumbs} id="market-breadcrumbs" />
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
      />
      <script
        type="application/ld+json"
        suppressHydrationWarning
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            itemListElement: [
              { "@type": "ListItem", position: 1, name: "Home", item: absoluteUrl("/") },
          { "@type": "ListItem", position: 2, name: "Events", item: absoluteUrl("/search") },
              { "@type": "ListItem", position: 3, name: market.title, item: absoluteUrl(canonicalPath) },
            ],
          }),
        }}
      />
    </>
  );
}
