"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { MarketDetail, MarketSibling } from "@/lib/api-types";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";
import { MarketDetailChart } from "@/components/markets/MarketDetailChart";
import { GroupedMarketSelector } from "@/components/markets/GroupedMarketSelector";
import { getCommitDeadline, resolvePriceStreamMarketId } from "@/lib/markets";
import { formatDateTime } from "@/lib/formatters";
import { buildBreadcrumbJsonLd } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";

type Props = {
  initialMarket: MarketDetail;
  initialOutcome?: number | null;
  fallbackEventId: string;
  canonicalEventId: string;
  canonicalPath: string;
  coverImage?: string;
  contextCopy: string;
};

export function EventDetailClient({
  initialMarket,
  initialOutcome,
  fallbackEventId,
  canonicalEventId,
  canonicalPath,
  coverImage,
  contextCopy,
}: Props) {
  const [market, setMarket] = useState<MarketDetail>(initialMarket);
  const [eventTitle, setEventTitle] = useState<string>(
    initialMarket.groupTitle || initialMarket.title,
  );
  const [activeEventId, setActiveEventId] = useState<string>(initialMarket.eventId ?? fallbackEventId);
  const [requestedOutcome, setRequestedOutcome] = useState<number | null>(
    typeof initialOutcome === "number" && Number.isFinite(initialOutcome) ? initialOutcome : null,
  );
  const [groupMarkets, setGroupMarkets] = useState<MarketDetail[]>(
    Array.isArray(initialMarket.groupMarkets) && initialMarket.groupMarkets.length > 0
      ? initialMarket.groupMarkets
      : [initialMarket],
  );

  const selectionCutoff = useMemo(() => Date.now(), []);
  const isSelectableMarket = useCallback((item: MarketDetail) => {
    const status = (item.status ?? "").toLowerCase();
    if (
      ["locked", "settled", "resolved", "cancelled", "canceled", "voided", "closed", "ended"].includes(status)
    ) {
      return false;
    }
    const candidates = [item.commitDeadline, item.closesAt]
      .map((value) => (value ? Date.parse(value) : NaN))
      .filter((value) => Number.isFinite(value));
    if (!candidates.length) return status === "" || status === "open" || status === "commit";
    return Math.min(...candidates) >= selectionCutoff;
  }, [selectionCutoff]);

  useEffect(() => {
    const nextGroup =
      Array.isArray(initialMarket.groupMarkets) && initialMarket.groupMarkets.length > 0
        ? initialMarket.groupMarkets
        : [initialMarket];
    setGroupMarkets(nextGroup);
    const resolvedTitle =
      nextGroup.find((item) => item.groupTitle)?.groupTitle ||
      nextGroup.find((item) => (item.groupItemTitle ?? "").toLowerCase().includes("match"))?.title ||
      nextGroup.find((item) => !item.groupItemTitle)?.title ||
      initialMarket.groupTitle ||
      initialMarket.title;
    setEventTitle(resolvedTitle);
    const nextActive = nextGroup.find(isSelectableMarket) ?? initialMarket;
    setMarket(nextActive);
    setActiveEventId(nextActive.eventId ?? fallbackEventId);
  }, [initialMarket, fallbackEventId, isSelectableMarket]);

  const handleSelect = useCallback((eventId: string) => {
    if (!eventId || eventId === activeEventId) return;
    const next = groupMarkets.find((item) => item.eventId === eventId);
    if (!next || !isSelectableMarket(next)) return;
    setMarket(next);
    setActiveEventId(eventId);
    setRequestedOutcome(null);
  }, [activeEventId, groupMarkets, isSelectableMarket]);

  if (!market) {
    return null;
  }

  const tokenIds = Array.isArray(market.clobTokenIds) ? market.clobTokenIds.map((t) => String(t)) : [];
  const priceStreamEventId = resolvePriceStreamMarketId(market, activeEventId);
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
  const selectorSiblings: MarketSibling[] =
    groupMarkets.length > 0
      ? groupMarkets.map((item) => ({
          eventId: item.eventId,
          title: item.title,
          status: item.status,
          groupItemTitle: item.groupItemTitle ?? null,
          groupItemThreshold: item.groupItemThreshold ?? null,
          groupPosition: item.groupPosition ?? null,
          outcomePrices: item.outcomePrices ?? [],
          volume: item.volume ?? 0,
          volume24hUsd: item.volume24hUsd ?? null,
          liquidityUsd: item.liquidityUsd ?? null,
          commitDeadline: getCommitDeadline(item) ?? item.closesAt ?? item.commitDeadline ?? null,
          startsAt: item.startsAt ?? null,
          closesAt: item.closesAt ?? null,
        }))
      : [
          {
            eventId: activeEventId,
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

  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Events", path: "/search" },
    { name: market.title, path: canonicalPath },
  ]);

  return (
    <>
      <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-16 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
          <MarketDetailHeader
            market={{
              ...market,
              groupTitle: eventTitle,
            }}
            coverImage={coverImage}
          />
          <div className="grid gap-6 lg:grid-cols-[1.7fr,1fr]">
            <div className="space-y-6">
              <GroupedMarketSelector
                groupSlug={market.groupSlug ?? canonicalEventId}
                siblings={selectorSiblings}
                activeEventId={activeEventId}
                onSelect={handleSelect}
                labelOverride="Grouped market"
                titleOverride={market.groupSlug ? undefined : market.title}
                subtitleOverride="Choose a sub-market within this event."
                forceShow
              />
              <MarketDetailChart
                key={`${activeEventId}-${market.conditionId ?? "market"}`}
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
            </div>
            <div className="space-y-4">
              <div id="trade-panel" className="relative">
                <div className="absolute inset-x-0 top-0 h-8 bg-gradient-to-b from-slate-950/95 to-transparent" aria-hidden />
                <div className="sticky top-6 z-10 self-start">
                  <StakeQuoteCard
                    key={activeEventId}
                    marketAddress={market.marketAddress}
                    marketId={activeEventId}
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
      </div>
      <JsonLd data={breadcrumbs} id="market-breadcrumbs" />
    </>
  );
}
