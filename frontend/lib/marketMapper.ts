import type { MarketSummary } from "./api-types";

export function mapApiMarketToSummary(item: any): MarketSummary {
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
  };
}
