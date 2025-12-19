"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api-types";
import { MarketGrid } from "./MarketGrid";
import { Skeleton } from "../ui/Skeleton";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "./constants";
import { useFeaturedMarkets } from "@/hooks/useFeaturedMarkets";
import { logger } from "@/lib/logging";
import { fetchFeaturedMarkets } from "@/lib/api";
import { categorySlugFromLabel } from "@/lib/slugs";
import type { MarketSortOption } from "@/lib/markets";

/**
 * We auto-load up to five batches via IntersectionObserver to give users a lazy-loading feel
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
  status?: string;
  onlyActive?: boolean;
  trending?: boolean;
  sortBy?: MarketSortOption;
  closesWithinHours?: number | null;
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
  status = "active",
  onlyActive = true,
  trending,
  sortBy = "totalVolume",
  closesWithinHours,
}: ClientProps) {
  const [markets, setMarkets] = useState<MarketSummary[]>(initialMarkets);
  const [hasMore, setHasMore] = useState<boolean>(initialMarkets.length >= pageSize);
  const [offset, setOffset] = useState(initialMarkets.length);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [autoLoadCount, setAutoLoadCount] = useState(0);
  const [autoLoadTriggered, setAutoLoadTriggered] = useState(false);
  const [showLoadingState, setShowLoadingState] = useState(false);
  const [isPending, startTransition] = useTransition();
  const [intersectionSupported, setIntersectionSupported] = useState(
    typeof window !== "undefined" && "IntersectionObserver" in window,
  );
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const setSentinel = useCallback((node: HTMLDivElement | null) => {
    sentinelRef.current = node;
  }, []);

  const batchSize = Math.max(pageSize, 30);
  const remainingSlots = useMemo(() => Math.max(0, maxItems - markets.length), [markets.length, maxItems]);
  const orderBy = "volume";
  const filterSignature = `${searchQuery ?? ""}|${categoryFilter ?? ""}|${pageSize}|${status}|${onlyActive}|${trending ?? "auto"}|${sortBy}|${closesWithinHours ?? "default"}`;

  const normalizedCategory = categoryFilter ? categorySlugFromLabel(categoryFilter) ?? categoryFilter : undefined;

  const filterByStatus = useCallback(
    (items: MarketSummary[]) =>
      onlyActive
        ? items.filter((m) => {
            const normalizedStatus = (m.status ?? "").toLowerCase();
            return (
              normalizedStatus === "" ||
              normalizedStatus === "active" ||
              normalizedStatus === "open" ||
              normalizedStatus === "live" ||
              normalizedStatus === "commit"
            );
          })
        : items,
    [onlyActive],
  );
  const normalizeMarkets = useCallback(
    (items: MarketSummary[]) => {
      const seen = new Set<string>();
      const filtered = filterByStatus(items).filter((item) => {
        if (!item.eventId || seen.has(item.eventId)) {
          return false;
        }
        seen.add(item.eventId);
        return true;
      });
      return filtered.slice(0, maxItems);
    },
    [filterByStatus, maxItems],
  );

  const { data: refreshedMarkets } = useFeaturedMarkets({
    limit: pageSize,
    searchQuery,
    category: normalizedCategory,
    status,
    trending,
    closesWithinHours,
    orderBy,
    initialData: initialMarkets,
  });

  useEffect(() => {
    // Always kick off a refresh when the component mounts so SSR payloads stay current.
    const seeded = normalizeMarkets([...initialMarkets]);
    const initialLikelyMore = initialMarkets.length >= pageSize || seeded.length >= pageSize;
    setMarkets(seeded);
    setHasMore(initialLikelyMore && seeded.length < maxItems);
    setOffset(initialMarkets.length);
    setAutoLoadCount(0);
    setAutoLoadTriggered(false);
    setIsLoadingMore(false);
  }, [initialMarkets, pageSize, maxItems, filterSignature, normalizeMarkets]);

  useEffect(() => {
    setIntersectionSupported(typeof window !== "undefined" && "IntersectionObserver" in window);
  }, []);

  useEffect(() => {
    if (!refreshedMarkets) {
      return;
    }
    setMarkets((prev) => {
      const merged = normalizeMarkets([...(refreshedMarkets || []), ...prev]);
      return merged;
    });
  }, [refreshedMarkets, normalizeMarkets]);

  const handleLoadMore = useCallback(
    (mode: "auto" | "manual" = "manual") => {
      const nextLimit = Number.isFinite(remainingSlots) ? Math.min(batchSize, remainingSlots) : batchSize;
      if (!hasMore || isPending || isLoadingMore || nextLimit <= 0) return;
      if (mode === "auto") {
        setAutoLoadTriggered(true);
      }
      const fetchOffset = offset;
      setIsLoadingMore(true);
      setShowLoadingState(true);
      startTransition(async () => {
        try {
          const additions = await fetchFeaturedMarkets(nextLimit, {
            searchQuery,
            category: normalizedCategory,
            offset: fetchOffset,
            status,
            trending,
            coalesceGroups: false,
            orderBy,
            closesWithinHours,
          });
          const merged = normalizeMarkets([...markets, ...additions]);
          const newItemsAdded = merged.length - markets.length;
          const computedHasMore = additions.length > 0 && merged.length < maxItems;
          setMarkets(merged);
          setOffset(fetchOffset + additions.length);
          setHasMore(computedHasMore);
          if (mode === "auto" && newItemsAdded > 0) {
            setAutoLoadTriggered(true);
            setAutoLoadCount((count) => count + 1);
          }
        } catch (error) {
          logger.clientError("FeaturedMarketsClient:loadMore_failed", { error: (error as Error).message });
          setHasMore(false);
        } finally {
          setIsLoadingMore(false);
          setShowLoadingState(false);
        }
      });
    },
    [
      normalizedCategory,
      hasMore,
      isPending,
      isLoadingMore,
      markets,
      maxItems,
      remainingSlots,
      offset,
      searchQuery,
      status,
      trending,
      normalizeMarkets,
      batchSize,
      orderBy,
      maxItems,
    ],
  );

  const isBusy = isPending || isLoadingMore;
  const canAutoLoad = intersectionSupported && hasMore && autoLoadCount < AUTO_LOAD_BATCHES;
  const showManualButton =
    markets.length > 0 && hasMore && (!intersectionSupported || autoLoadCount >= AUTO_LOAD_BATCHES);
  const showLoadingIndicator = showLoadingState && !showManualButton;

  useEffect(() => {
    if (!canAutoLoad || isBusy) {
      return;
    }
    const target = sentinelRef.current;
    if (!target) {
      return;
    }
    if (typeof IntersectionObserver === "undefined") {
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
  }, [canAutoLoad, handleLoadMore, isBusy, markets.length]);

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
      {hasMore && <div ref={setSentinel} aria-hidden className="h-6 w-full" />}
      {showLoadingIndicator && (
        <div
          className="flex items-center justify-center text-sm text-slate-300"
          role="status"
          data-testid="auto-loading-indicator"
        >
          Loading...
        </div>
      )}
    {showManualButton && (
      <div className="flex items-center justify-center">
        <button
          type="button"
          disabled={!hasMore || isBusy}
          aria-busy={isBusy}
          onClick={() => handleLoadMore("manual")}
          className="appearance-none rounded-full border border-white/20 bg-transparent px-6 py-2 text-sm font-semibold text-white transition hover:border-brand-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/50 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isBusy ? "Loading..." : hasMore ? "Load more markets" : "All markets loaded"}
        </button>
      </div>
    )}
  </section>
);
}
