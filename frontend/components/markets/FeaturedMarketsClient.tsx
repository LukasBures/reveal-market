"use client";

import { useEffect, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api";
import { MarketGrid } from "./MarketGrid";
import { Skeleton } from "../ui/Skeleton";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "./constants";

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
  const [isPending, startTransition] = useTransition();
  const remainingSlots = maxItems - markets.length;
  const nextLimit = Math.min(pageSize, remainingSlots);

  useEffect(() => {
    setMarkets(initialMarkets);
    setHasMore(initialMarkets.length >= pageSize);
  }, [initialMarkets, pageSize]);

  const handleLoadMore = () => {
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
        setMarkets((prev) => {
          const seen = new Set(prev.map((m) => m.eventId));
          const merged = [...prev];
          for (const item of payload) {
            const id = item.event_id ?? item.eventId;
            if (!id || seen.has(id)) continue;
            merged.push({
              eventId: id,
              title: item.title ?? "Untitled market",
              category: item.category ?? item.tags?.[0] ?? "General",
              tags: item.tags ?? [],
              status: item.status ?? undefined,
              commitDeadline: item.commit_deadline ?? undefined,
              revealDeadline: item.reveal_deadline ?? undefined,
              liquidityUsd: item.extra_data?.liquidityUsd ?? item.liquidity_usd,
              outcomes: item.outcomes ?? [],
              outcomePrices: item.outcome_prices ?? [],
              imageUrl: item.image_url ?? null,
            });
            seen.add(id);
          }
          if (merged.length >= maxItems) {
            setHasMore(false);
          } else if (payload.length < nextLimit) {
            setHasMore(false);
          }
          return merged;
        });
      } catch (error) {
        console.error("Unable to load additional markets", error);
        setHasMore(false);
      }
    });
  };

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
      {markets.length > 0 && hasMore && (
        <div className="flex items-center justify-center">
          <button
            type="button"
            disabled={!hasMore || isPending}
            onClick={handleLoadMore}
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
