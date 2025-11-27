"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api-types";
import { MarketGrid } from "./MarketGrid";
import { Skeleton } from "../ui/Skeleton";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "./constants";
import { useFeaturedMarkets } from "@/hooks/useFeaturedMarkets";
import { logger } from "@/lib/logging";
import { loadFeaturedMarketsAction } from "@/app/actions/markets";
import { categorySlugFromLabel } from "@/lib/slugs";

/**
 * We auto-load up to three batches via IntersectionObserver to give users a lazy-loading feel
 * before they need to press the button. After that the CTA becomes the explicit interaction.
 */
export const AUTO_LOAD_BATCHES = 5;

type ClientProps = {
  initialMarkets: MarketSummary[];
  pageSize?: number;
  maxItems?: number;
  searchQuery?: string;
  categoryFilter?: string;
  emptyNotice?: string;
};

/**
 * Client component that hydrates featured markets with lazy loading, auto-refresh, and pagination.
 */
export function FeaturedMarketsClient({
  initialMarkets,
  pageSize = DEFAULT_PAGE_SIZE,
  maxItems = DEFAULT_MAX_ITEMS,
  searchQuery,
  categoryFilter,
  emptyNotice,
}: ClientProps) {
  const [markets, setMarkets] = useState<MarketSummary[]>(initialMarkets);
  const [hasMore, setHasMore] = useState<boolean>(initialMarkets.length >= pageSize);
  const [autoLoadCount, setAutoLoadCount] = useState(0);
  const [isPending, startTransition] = useTransition();
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const DEFAULT_BATCH = 40;
  const remainingSlots = useMemo(() => Math.max(0, maxItems - markets.length), [markets.length, maxItems]);
  const filterSignature = `${searchQuery ?? ""}|${categoryFilter ?? ""}|${pageSize}`;

  const normalizedCategory = categoryFilter ? categorySlugFromLabel(categoryFilter) ?? categoryFilter : undefined;

  const { data: refreshedMarkets } = useFeaturedMarkets({
    limit: pageSize,
    searchQuery,
    category: normalizedCategory,
    initialData: initialMarkets,
  });

  useEffect(() => {
    // Always kick off a refresh when the component mounts so SSR payloads stay current.
    setMarkets(initialMarkets);
    setHasMore(initialMarkets.length >= pageSize);
    setAutoLoadCount(0);
  }, [initialMarkets, pageSize, filterSignature]);

  useEffect(() => {
    if (!refreshedMarkets) {
      return;
    }
    setMarkets((prev) => {
      const seen = new Set<string>();
      const merged: MarketSummary[] = [];
      const pushUnique = (item: MarketSummary) => {
        if (!item.eventId || seen.has(item.eventId)) {
          return;
        }
        seen.add(item.eventId);
        merged.push(item);
      };
      refreshedMarkets.forEach(pushUnique);
      prev.forEach(pushUnique);
      return merged.slice(0, maxItems);
    });
  }, [refreshedMarkets, maxItems]);

  const handleLoadMore = useCallback(
    (mode: "auto" | "manual" = "manual") => {
      if (!hasMore || isPending || remainingSlots <= 0) return;
      const nextLimit = DEFAULT_BATCH;
      startTransition(async () => {
        try {
          const additions = await loadFeaturedMarketsAction(nextLimit, {
            searchQuery,
            category: normalizedCategory,
            offset: markets.length,
          });
          if (additions.length === 0) {
            setHasMore(false);
            return;
          }
          const seen = new Set(markets.map((m) => m.eventId));
          const filtered: MarketSummary[] = [];
          for (const item of additions) {
            if (!item.eventId || seen.has(item.eventId)) continue;
            seen.add(item.eventId);
            filtered.push(item);
          }
          const allowed = Math.max(0, maxItems - markets.length);
          const nextItems = allowed > 0 ? filtered.slice(0, allowed) : [];
          const merged = [...markets, ...nextItems];
          const computedHasMore =
            merged.length < maxItems && nextItems.length > 0 && additions.length === nextLimit;
          setMarkets(merged);
          setHasMore(computedHasMore);
          if (mode === "auto" && nextItems.length > 0) {
            setAutoLoadCount((count) => count + 1);
          }
        } catch (error) {
          logger.clientError("FeaturedMarketsClient:loadMore_failed", { error: (error as Error).message });
          setHasMore(false);
        }
      });
    },
    [normalizedCategory, hasMore, isPending, markets, maxItems, remainingSlots, searchQuery],
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
            className="appearance-none rounded-full border border-white/20 bg-transparent px-6 py-2 text-sm font-semibold text-white transition hover:border-brand-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/50 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isPending ? "Loading…" : hasMore ? "Load more markets" : "All markets loaded"}
          </button>
        </div>
      )}
      {!hasMore && markets.length > 0 && (
        <p className="text-center text-sm text-slate-400">
          Looking for deeper narratives? Use the category filters above to jump into the segments that matter most.
        </p>
      )}
    </section>
  );
}
