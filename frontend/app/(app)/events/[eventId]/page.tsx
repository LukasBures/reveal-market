import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { EventDetailClient } from "@/components/events/EventDetailClient";
import { fetchFeaturedEvents, fetchMarketByEventId } from "@/lib/api";
import type { MarketDetail } from "@/lib/api-types";
import { absoluteUrl, buildMetadata } from "@/lib/seo";
import { getCommitDeadline } from "@/lib/markets";

export const revalidate = 60;
export const dynamic = "force-static";

type MarketDetailParams = {
  eventId: string;
};

type MarketDetailPageProps = {
  params: Promise<MarketDetailParams>;
  searchParams?: Promise<{ outcome?: string; eventId?: string; event_id?: string }>;
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
  market.groupSlug && market.groupSlug !== "unknown" ? market.groupSlug : fallback;

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
  const requestedEventId =
    typeof resolvedSearchParams?.eventId === "string"
      ? resolvedSearchParams.eventId
      : typeof resolvedSearchParams?.event_id === "string"
        ? resolvedSearchParams.event_id
        : null;
  const requestedOutcome = resolvedSearchParams?.outcome ? Number(resolvedSearchParams.outcome) : null;
  const lookupKey = requestedEventId ?? eventId;
  const market = await loadEvent(lookupKey);
  if (!market) {
    notFound();
  }
  const canonicalEventId = getCanonicalEventId(market, eventId);
  const canonicalPath = buildEventPath(canonicalEventId);
  const contextCopy = selectEventCopy(market);
  const structuredData = buildEventStructuredData(market, contextCopy, canonicalPath);
  const coverImage = resolveEventImage(market);
  return (
    <>
      <EventDetailClient
        initialMarket={market}
        initialOutcome={requestedOutcome}
        fallbackEventId={eventId}
        canonicalEventId={canonicalEventId}
        canonicalPath={canonicalPath}
        coverImage={coverImage}
        contextCopy={contextCopy}
      />
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
