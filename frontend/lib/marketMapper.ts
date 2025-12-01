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
    item.volume_24h_usd ??
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
  const liquidity =
    Number(item.liquidity_usd ?? item.liquidityUsd ?? item.extra_data?.liquidity_usd ?? 0) || undefined;
  const orderbookVolumeUsd =
    Number(item.orderbook_volume_usd ?? item.orderbookVolumeUsd ?? item.extra_data?.orderbook_volume_usd ?? 0) ||
    undefined;
  const tradesQuantity =
    typeof item.trades_quantity === "number"
      ? item.trades_quantity
      : typeof item.tradesQuantity === "number"
        ? item.tradesQuantity
        : undefined;
  const gammaImage =
    item.extra_data?.image_url ??
    item.extra_data?.gamma?.image_url ??
    item.extra_data?.gamma?.imageUrl ??
    item.extra_data?.gamma?.cover_image ??
    item.extra_data?.gamma?.coverImage;
  const groupSlug = item.group_slug ?? item.groupSlug ?? null;
  const rawGroupThreshold = Number(item.group_item_threshold ?? item.groupItemThreshold);
  const groupItemThreshold = Number.isFinite(rawGroupThreshold) ? rawGroupThreshold : null;
  const rawGroupPosition = Number(item.group_position ?? item.groupPosition);
  const groupPosition = Number.isFinite(rawGroupPosition) ? rawGroupPosition : null;
  const siblings = Array.isArray(item.siblings)
    ? item.siblings.map((sibling: any) => {
        const siblingThreshold = Number(sibling.group_item_threshold ?? sibling.groupItemThreshold);
        const siblingPosition = Number(sibling.group_position ?? sibling.groupPosition);
        const siblingVolume = Number(sibling.volume_24h_usd ?? sibling.volume24hUsd);
        const siblingLiquidity = Number(sibling.liquidity_usd ?? sibling.liquidityUsd);
        return {
          eventId: sibling.event_id ?? sibling.eventId ?? "unknown",
          title: sibling.title ?? undefined,
          groupItemTitle: sibling.group_item_title ?? sibling.groupItemTitle ?? null,
          groupItemThreshold: Number.isFinite(siblingThreshold) ? siblingThreshold : null,
          groupPosition: Number.isFinite(siblingPosition) ? siblingPosition : null,
          outcomePrices: sibling.outcome_prices ?? sibling.outcomePrices ?? null,
          volume24hUsd: Number.isFinite(siblingVolume) ? siblingVolume : null,
          liquidityUsd: Number.isFinite(siblingLiquidity) ? siblingLiquidity : null,
        };
      })
    : undefined;
  return {
    eventId: item.event_id ?? item.eventId ?? "unknown",
    title: item.title ?? "Untitled market",
    category: item.category ?? item.tags?.[0] ?? "General",
    tags: item.tags ?? item.extra_data?.tags ?? [],
    status: item.status ?? undefined,
    commitDeadline:
      item.commit_deadline ??
      item.commitDeadline ??
      item.closes_at ??
      item.closesAt ??
      item.orders_opened_at ??
      item.ordersOpenedAt ??
      item.extra_data?.commit_deadline ??
      item.extra_data?.gamma?.commit_deadline ??
      item.extra_data?.gamma?.commitDeadline ??
      item.extra_data?.closes_at ??
      item.extra_data?.closesAt ??
      item.extra_data?.gamma?.closes_at ??
      item.extra_data?.gamma?.closesAt ??
      item.extra_data?.orders_opened_at ??
      item.extra_data?.gamma?.orders_opened_at ??
      item.extra_data?.gamma?.ordersOpenedAt ??
      undefined,
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
    featured:
      typeof item.featured === "boolean"
        ? item.featured
        : typeof item.extra_data?.featured === "boolean"
          ? item.extra_data.featured
          : typeof item.extra_data?.gamma?.featured === "boolean"
            ? item.extra_data.gamma.featured
            : null,
    clobTokenIds:
      normalizeClobTokenIds(item.clob_token_ids) ??
      normalizeClobTokenIds(item.clobTokenIds) ??
      normalizeClobTokenIds(item.extra_data?.gamma?.clob_token_ids) ??
      normalizeClobTokenIds(item.extra_data?.gamma?.clobTokenIds) ??
      null,
    imageVariants: item.image_variants ?? item.imageVariants ?? null,
    volume24hUsd,
    orderbookVolumeUsd,
    tradesQuantity,
    groupSlug,
    groupItemTitle: item.group_item_title ?? item.groupItemTitle ?? null,
    groupItemThreshold,
    groupPosition,
    siblings,
  };
}
