"use client";

import { useCallback, useEffect, useMemo, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import type { MarketDetail, MarketSibling } from "@/lib/api-types";
import { MarketDetailHeader } from "@/components/markets/MarketDetailHeader";
import { StakeQuoteCard } from "@/components/markets/StakeQuoteCard";
import { GroupedMarketSelector } from "@/components/markets/GroupedMarketSelector";
import { getCommitDeadline } from "@/lib/markets";
import { formatDateTime, formatUsd, formatUsdCompact } from "@/lib/formatters";
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
  const [selectedOutcome, setSelectedOutcome] = useState<number>(
    typeof initialOutcome === "number" && Number.isFinite(initialOutcome) ? initialOutcome : 0,
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
    setSelectedOutcome(0);
  }, [activeEventId, groupMarkets, isSelectableMarket]);

  const commitDeadline = getCommitDeadline(market);
  const initialOutcomeId =
    typeof requestedOutcome === "number" && Number.isFinite(requestedOutcome) && requestedOutcome >= 0
      ? Math.min(requestedOutcome, (market.outcomes?.length ?? 1) - 1)
      : 0;
  useEffect(() => {
    if (typeof requestedOutcome === "number" && Number.isFinite(requestedOutcome)) {
      setSelectedOutcome(Math.min(Math.max(requestedOutcome, 0), (market.outcomes?.length ?? 1) - 1));
    }
  }, [requestedOutcome, market.outcomes?.length]);
  if (!market) {
    return null;
  }
  const resolutionCheckedAt = market.resolution?.checkedAt ?? null;
  const resolutionLabel = market.resolution?.resolved ? "Resolved" : market.status ?? "Active";
  const detailRows = [
    { label: "Open interest", value: formatUsdCompact(market.openInterestUsd ?? market.openInterest) },
    { label: "24h volume", value: formatUsd(market.volume24hUsd ?? market.orderbookVolumeUsd) },
    { label: "Total volume", value: formatUsd(market.volume ?? market.orderbookVolumeUsd) },
    { label: "Liquidity", value: formatUsd(market.liquidityUsd) },
    { label: "Status", value: resolutionLabel },
    { label: "Commit deadline", value: commitDeadline ? formatDateTime(commitDeadline) : "TBA" },
    { label: "Reveal deadline", value: market.revealDeadline ? formatDateTime(market.revealDeadline) : "TBA" },
    { label: "Resolved at", value: resolutionCheckedAt ? formatDateTime(resolutionCheckedAt) : "—" },
  ];
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
      <Suspense fallback={null}>
        <OutcomeParamReader initialOutcome={initialOutcome} onOutcome={setRequestedOutcome} />
      </Suspense>
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
            <div className="space-y-6 lg:self-start">
              <GroupedMarketSelector
                groupSlug={canonicalEventId}
                siblings={selectorSiblings}
                activeEventId={activeEventId}
                onSelectAction={handleSelect}
                marketDetails={groupMarkets}
                selectedOutcome={selectedOutcome}
                subtitleOverride="Choose a sub-market within this event."
                forceShow
              />
              <section className="rounded-3xl border border-slate-800 bg-slate-950 p-6 text-sm text-slate-300">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Event context</p>
                    <div className="mt-3 space-y-3 text-slate-200">
                      <p className="text-sm font-semibold text-white">Resolution criteria</p>
                      <div className="whitespace-pre-line text-sm leading-relaxed text-slate-200">{contextCopy}</div>
                    </div>
                  </div>
                </div>
              </section>
              <section className="rounded-3xl border border-slate-800 bg-slate-950 p-6 text-sm text-slate-300">
                <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Market details</p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {detailRows.map((row) => (
                    <div key={row.label} className="flex items-center justify-between rounded-2xl border border-white/10 bg-slate-950/50 px-4 py-3">
                      <span className="text-xs uppercase tracking-[0.2em] text-slate-500">{row.label}</span>
                      <span className="text-sm font-semibold text-white">{row.value}</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
            <div className="relative space-y-4 lg:self-stretch">
              <div id="trade-panel" className="self-start lg:sticky lg:top-[88px]">
                <StakeQuoteCard
                  marketAddress={market.marketAddress}
                  marketId={activeEventId}
                  outcomes={market.outcomes ?? []}
                  outcomePrices={market.outcomePrices ?? []}
                  initialOutcomeId={initialOutcomeId}
                  marketTitle={market.title}
                  marketStatus={market.status}
                  isResolved={market.resolution?.resolved ?? null}
                  onOutcomeChangeAction={setSelectedOutcome}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
      <JsonLd data={breadcrumbs} id="market-breadcrumbs" />
    </>
  );
}

function OutcomeParamReader({
  initialOutcome,
  onOutcome,
}: {
  initialOutcome: number | null | undefined;
  onOutcome: (id: number) => void;
}) {
  const searchParams = useSearchParams();
  useEffect(() => {
    if (typeof initialOutcome === "number" && Number.isFinite(initialOutcome)) return;
    const outcomeParam = searchParams.get("outcome");
    if (outcomeParam === null) return;
    const parsed = Number(outcomeParam);
    if (Number.isFinite(parsed) && parsed >= 0) onOutcome(parsed);
  }, [searchParams, initialOutcome, onOutcome]);
  return null;
}
