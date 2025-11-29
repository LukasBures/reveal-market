import type { MarketSummary } from "./api-types";

const normalizeClobTokenIds = (value: any): string[] | null => {
  if (Array.isArray(value)) {
    return value.map((v) => String(v));
  }
  if (typeof value === "string") {
    // Try JSON array first.
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map((v) => String(v));
      }
    } catch {
      // Fallback to comma-separated.
      const parts = value.split(",").map((v) => v.trim()).filter(Boolean);
      if (parts.length) return parts;
    }
  }
  return null;
};

export function mapApiMarketToSummary(item: any): MarketSummary {
  const volumeCandidate =
    item.volume24h ??
    item.volume_24h ??
    item.volume24hr ??
    item.volume ??
    item.extra_data?.gamma?.volume24hr ??
    item.extra_data?.volume24hr ??
    item.extra_data?.volume ??
    item.extra_data?.gamma?.volume ??
    0;
  const volume24hUsd = Number(volumeCandidate) || 0;
  const liquidity = Number(item.liquidity_usd ?? item.liquidityUsd ?? item.extra_data?.liquidity_usd ?? 0) || 0;
  const popularityScore = Math.max(volume24hUsd, liquidity, 0);
  const gammaImage =
    item.extra_data?.image_url ??
    item.extra_data?.gamma?.image_url ??
    item.extra_data?.gamma?.imageUrl ??
    item.extra_data?.gamma?.cover_image ??
    item.extra_data?.gamma?.coverImage;
  return {
    eventId: item.event_id ?? item.eventId ?? "unknown",
    title: item.title ?? "Untitled market",
    category: item.category ?? item.tags?.[0] ?? "General",
    tags: item.tags ?? item.extra_data?.tags ?? [],
    status: item.status ?? undefined,
    commitDeadline: item.commit_deadline ?? item.commitDeadline ?? undefined,
    revealDeadline: item.reveal_deadline ?? item.revealDeadline ?? undefined,
    liquidityUsd: item.liquidity_usd ?? item.liquidityUsd ?? item.extra_data?.liquidity_usd ?? undefined,
    outcomes: item.outcomes ?? item.extra_data?.outcomes ?? [],
    outcomePrices: item.outcome_prices ?? item.extra_data?.outcome_prices ?? [],
    imageUrl: item.image_url ?? item.imageUrl ?? gammaImage ?? null,
    rakeBps: item.rake_bps ?? item.rakeBps ?? null,
    extraData: item.extra_data ?? item.extraData ?? null,
    closesAt: item.closes_at ?? item.closesAt ?? item.extra_data?.gamma?.closesAt ?? null,
    startsAt: item.starts_at ?? item.startsAt ?? item.extra_data?.gamma?.startDate ?? null,
    ordersOpenedAt: item.orders_opened_at ?? item.ordersOpenedAt ?? null,
    resolutionSource: item.resolution_source ?? item.resolutionSource ?? null,
    marketMaker: item.market_maker ?? item.marketMaker ?? null,
    orderMinSize: item.order_min_size ?? item.orderMinSize ?? null,
    priceTickSize: item.price_tick_size ?? item.priceTickSize ?? null,
    enableOrderBook:
      typeof item.enable_order_book === "boolean"
        ? item.enable_order_book
        : typeof item.enableOrderBook === "boolean"
          ? item.enableOrderBook
          : null,
    clobTokenIds:
      normalizeClobTokenIds(item.clob_token_ids) ??
      normalizeClobTokenIds(item.clobTokenIds) ??
      normalizeClobTokenIds(item.extra_data?.gamma?.clob_token_ids) ??
      normalizeClobTokenIds(item.extra_data?.gamma?.clobTokenIds) ??
      null,
    imageVariants: item.image_variants ?? item.imageVariants ?? null,
    popularityScore,
    volume24hUsd,
  };
}
