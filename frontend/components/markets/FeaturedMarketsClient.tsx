"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api";
import { MarketGrid } from "./MarketGrid";
import { Skeleton } from "../ui/Skeleton";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "./constants";

const AUTO_LOAD_BATCHES = 3;

type ClientProps = {
  initialMarkets: MarketSummary[];
  pageSize?: number;
  maxItems?: number;
  searchQuery?: string;
  categoryFilter?: string;
  tagFilter?: string;
  emptyNotice?: string;
};

export function FeaturedMarketsClient({
  initialMarkets,
  pageSize = DEFAULT_PAGE_SIZE,
  maxItems = DEFAULT_MAX_ITEMS,
  searchQuery,
  categoryFilter,
  tagFilter,
  emptyNotice,
}: ClientProps) {
  const [markets, setMarkets] = useState<MarketSummary[]>(initialMarkets);
  const [hasMore, setHasMore] = useState<boolean>(initialMarkets.length >= pageSize);
  const [autoLoadCount, setAutoLoadCount] = useState(0);
  const [isPending, startTransition] = useTransition();
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const remainingSlots = useMemo(() => Math.max(0, maxItems - markets.length), [markets.length, maxItems]);

  useEffect(() => {
    setMarkets(initialMarkets);
    setHasMore(initialMarkets.length >= pageSize);
    setAutoLoadCount(0);
  }, [initialMarkets, pageSize]);

  const normalizePayload = (items: any[]): MarketSummary[] =>
    items.map((item) => ({
      eventId: item.event_id ?? item.eventId ?? "unknown",
      title: item.title ?? "Untitled market",
      category: item.category ?? item.tags?.[0] ?? "General",
      tags: item.tags ?? [],
      status: item.status ?? undefined,
      commitDeadline: item.commit_deadline ?? item.commitDeadline ?? undefined,
      revealDeadline: item.reveal_deadline ?? item.revealDeadline ?? undefined,
      liquidityUsd: item.extra_data?.liquidityUsd ?? item.liquidity_usd,
      outcomes: item.outcomes ?? [],
      outcomePrices: item.outcome_prices ?? [],
      imageUrl: item.image_url ?? null,
    }));

  const handleLoadMore = useCallback(
    (mode: "auto" | "manual" = "manual") => {
      const nextLimit = Math.min(pageSize, remainingSlots);
      if (!hasMore || isPending || nextLimit <= 0) return;
      startTransition(async () => {
        try {
          const offset = markets.length;
          const params = new URLSearchParams({ limit: String(nextLimit), offset: String(offset) });
          if (searchQuery) {
          params.set("search", searchQuery);
        }
        if (categoryFilter) {
          params.set("category", categoryFilter);
        }
        if (tagFilter) {
          params.set("tag", tagFilter);
        }
        const response = await fetch(`/markets?${params.toString()}`, { cache: "no-store" });
        if (!response.ok) {
          console.error("Failed to load more markets", response.status);
          setHasMore(false);
          return;
        }
        const payload = await response.json();
        if (!Array.isArray(payload) || payload.length === 0) {
          setHasMore(false);
          return;
        }
        const normalized = normalizePayload(payload);
        const seen = new Set(markets.map((m) => m.eventId));
        const additions: MarketSummary[] = [];
        for (const item of normalized) {
          if (!item.eventId || seen.has(item.eventId)) continue;
          seen.add(item.eventId);
          additions.push(item);
        }
        const merged = [...markets, ...additions];
        const computedHasMore =
          merged.length < maxItems && additions.length > 0 && normalized.length === nextLimit;
        setMarkets(merged);
        setHasMore(computedHasMore);
        if (mode === "auto" && normalized.length > 0) {
          setAutoLoadCount((count) => count + 1);
        }
      } catch (error) {
        console.error("Unable to load additional markets", error);
        setHasMore(false);
      }
    });
    },
    [categoryFilter, hasMore, isPending, markets, maxItems, pageSize, remainingSlots, searchQuery, tagFilter],
  );

  const canAutoLoad = hasMore && autoLoadCount < AUTO_LOAD_BATCHES;

  useEffect(() => {
    if (!canAutoLoad || isPending) {
      return;
    }
    const target = sentinelRef.current;
    if (!target) {
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          observer.disconnect();
          handleLoadMore("auto");
          break;
        }
      }
    }, { rootMargin: "200px" });
    observer.observe(target);
    return () => observer.disconnect();
  }, [canAutoLoad, handleLoadMore, isPending, markets.length]);

  const renderEmptyState = () => {
    if (emptyNotice) {
      return (
        <div className="rounded-3xl border border-dashed border-white/10 bg-slate-950/40 p-6 text-center text-sm text-slate-300">
          {emptyNotice}
        </div>
      );
    }
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-52 rounded-3xl border border-white/5 bg-white/5" />
        ))}
      </div>
    );
  };

  return (
    <section className="space-y-4">
      {markets.length === 0 ? (
        renderEmptyState()
      ) : (
        <MarketGrid markets={markets} />
      )}
      {canAutoLoad && <div ref={sentinelRef} aria-hidden className="h-6 w-full" />}
      {markets.length > 0 && hasMore && (
        <div className="flex items-center justify-center">
          <button
            type="button"
            disabled={!hasMore || isPending}
            onClick={() => handleLoadMore("manual")}
            className="rounded-full border border-white/20 px-6 py-2 text-sm font-semibold text-white transition hover:border-brand-400 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isPending ? "Loading…" : hasMore ? "Load more markets" : "All markets loaded"}
          </button>
        </div>
      )}
      {!hasMore && markets.length > 0 && (
        <p className="text-center text-sm text-slate-400">
          Looking for deeper categories? Use the filters above to jump into the tags that matter most.
        </p>
      )}
    </section>
  );
}
