"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import type { EventSummary } from "@/lib/api-types";
import { EventGrid } from "@/components/events/EventGrid";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "./constants";
import { logger } from "@/lib/logging";
import { fetchFeaturedEvents } from "@/lib/api";
import { categorySlugFromLabel } from "@/lib/slugs";
import { MARKET_CATEGORY_FILTERS, type MarketSortOption } from "@/lib/markets";

/**
 * We auto-load up to two batches via IntersectionObserver to give users a lazy-loading feel
 * before they need to press the button. After that the CTA becomes the explicit interaction.
 */
export const AUTO_LOAD_BATCHES = 2;

type ClientProps = {
  initialMarkets: EventSummary[];
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
 * Client component that hydrates featured events with lazy loading, auto-refresh, and pagination.
 */
export function FeaturedEventsClient({
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
  const [autoLoadCount, setAutoLoadCount] = useState(0);
  const [showLoadingState, setShowLoadingState] = useState(false);
  const [isPending, startTransition] = useTransition();
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [fetchHint, setFetchHint] = useState<"auto" | "manual" | null>(null);
  const [intersectionSupported, setIntersectionSupported] = useState(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const setSentinel = useCallback((node: HTMLDivElement | null) => {
    sentinelRef.current = node;
  }, []);

  const batchSize = Math.max(pageSize, 1);
  const orderBy = sortBy === "recent" ? "recent" : sortBy === "popularity" ? "popularity" : "volume";
  const filterSignature = `${searchQuery ?? ""}|${categoryFilter ?? ""}|${pageSize}|${status}|${onlyActive}|${trending ?? "auto"}|${sortBy}|${closesWithinHours ?? "default"}`;

  const normalizedCategory = categoryFilter ? categorySlugFromLabel(categoryFilter) ?? categoryFilter : undefined;

  const filterByStatus = useCallback(
    (items: EventSummary[]) =>
      onlyActive
        ? items.filter((m) => {
            const normalizedStatus = (m.markets?.[0]?.status ?? "").toLowerCase();
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
  const normalizeEvents = useCallback(
    (items: EventSummary[]) => {
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

  const queryKey = useMemo(
    () => [
      "featuredEvents",
      {
        limit: batchSize,
        searchQuery: searchQuery ?? null,
        category: normalizedCategory ?? null,
        status: status ?? "active",
        trending: trending ?? null,
        orderBy,
        closesWithinHours: closesWithinHours ?? null,
      },
    ],
    [batchSize, searchQuery, normalizedCategory, status, trending, orderBy, closesWithinHours],
  );

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey,
    queryFn: async ({ pageParam = 0 }) => {
      const result = await fetchFeaturedEvents(batchSize, {
        searchQuery,
        category: normalizedCategory,
        offset: pageParam,
        status,
        trending,
        orderBy,
        closesWithinHours,
      });
      if (result.error) {
        throw new Error(result.error);
      }
      return result.data;
    },
    initialPageParam: 0,
    initialData: {
      pages: [initialMarkets],
      pageParams: [0],
    },
    getNextPageParam: (lastPage, allPages) => {
      if (lastPage.length === 0) return undefined;
      // Use page-aligned offsets so cache keys match hydrated pages.
      const pageIndex = allPages.length;
      const nextOffset = pageIndex * batchSize;
      if (nextOffset >= maxItems) return undefined;
      return nextOffset;
    },
    staleTime: 30_000,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 5000),
    refetchOnWindowFocus: false,
  });

  const events = useMemo(() => {
    const pages = data?.pages ?? [];
    const flattened = pages.flatMap((page) => page);
    return normalizeEvents(flattened);
  }, [data?.pages, normalizeEvents]);

  useEffect(() => {
    // Always kick off a refresh when the component mounts so SSR payloads stay current.
    setAutoLoadCount(0);
    setShowLoadingState(false);
  }, [initialMarkets, pageSize, maxItems, filterSignature, normalizeEvents]);

  useEffect(() => {
    const hasObserver =
      (typeof window !== "undefined" && "IntersectionObserver" in window) ||
      (typeof globalThis !== "undefined" && "IntersectionObserver" in globalThis);
    setIntersectionSupported(hasObserver);
  }, []);

  const handleLoadMore = useCallback(
    (mode: "auto" | "manual" = "manual") => {
      if (!hasNextPage || isPending || isFetchingNextPage) return;
      setFetchHint(mode);
      setShowLoadingState(true);
      startTransition(() => {
        fetchNextPage()
          .then(() => {
            setLoadMoreError(null);
            if (mode === "auto") {
              setAutoLoadCount((count) => count + 1);
            }
          })
          .catch((error) => {
            logger.clientError("FeaturedEventsClient:loadMore_failed", { error: (error as Error).message });
            setLoadMoreError("Failed to load more events.");
          })
          .finally(() => {
            setShowLoadingState(false);
          });
      });
    },
    [
      fetchNextPage,
      hasNextPage,
      isPending,
      isFetchingNextPage,
    ],
  );

  const isBusy = isPending || isFetchingNextPage;
  const isAutoFetching = fetchHint === "auto" && isBusy;
  const canAutoLoad = intersectionSupported && hasNextPage && autoLoadCount < AUTO_LOAD_BATCHES;
  const showLoadingIndicator =
    showLoadingState && isAutoFetching && hasNextPage && intersectionSupported && autoLoadCount < AUTO_LOAD_BATCHES;
  const showManualButton = events.length > 0 && hasNextPage && !showLoadingIndicator && !isAutoFetching;

  useEffect(() => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!canAutoLoad || isBusy) {
      return;
    }
    const target = sentinelRef.current;
    if (!target || typeof IntersectionObserver === "undefined") {
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          observer.disconnect();
          observerRef.current = null;
          handleLoadMore("auto");
          break;
        }
      }
    }, { rootMargin: "400px" });
    observer.observe(target);
    observerRef.current = observer;
    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [canAutoLoad, handleLoadMore, isBusy, events.length]);

  useEffect(() => {
    if (!canAutoLoad || isBusy) return;
    if (events.length >= pageSize) return;
    handleLoadMore("auto");
  }, [canAutoLoad, events.length, handleLoadMore, isBusy, pageSize]);

  useEffect(() => {
    if (!isBusy) {
      setFetchHint(null);
    }
  }, [isBusy]);

  const renderEmptyState = () => {
    if (emptyNotice) {
      return (
        <div className="rounded-3xl border border-dashed border-white/10 bg-slate-950/40 p-6 text-center text-sm text-slate-300">
          {emptyNotice}
        </div>
      );
    }
    const currentLabel = (categoryFilter ?? "").toLowerCase();
    const suggestions = MARKET_CATEGORY_FILTERS.filter((c) => c.toLowerCase() !== currentLabel);
    return (
      <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-center text-sm text-slate-300">
        <p className="text-base font-semibold text-white">No markets match that yet.</p>
        <p className="mt-2 text-sm text-slate-400">Try a different category or clear filters to explore.</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {suggestions.map((category) => {
            const slug = categorySlugFromLabel(category) ?? category.toLowerCase().replace(/[^a-z0-9-]/g, "-");
            return (
              <a
                key={category}
                href={`/${encodeURIComponent(slug)}`}
                className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.25em] text-white/70 transition hover:border-brand-400/60 hover:text-white sm:py-1"
              >
                {category}
              </a>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <section className="space-y-4">
      {events.length === 0 ? (
        renderEmptyState()
      ) : (
        <EventGrid events={events} />
      )}
      {hasNextPage && <div ref={setSentinel} aria-hidden className="h-6 w-full" />}
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
            disabled={!hasNextPage || isBusy}
            aria-busy={isBusy}
            onClick={() => handleLoadMore("manual")}
            className="appearance-none rounded-full border border-white/20 bg-transparent px-6 py-2 text-sm font-semibold text-white transition hover:border-brand-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400/50 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {hasNextPage ? "Load more events" : "All events loaded"}
          </button>
        </div>
      )}
      {loadMoreError ? (
        <div className="flex flex-col items-center gap-2 py-4">
          <p className="text-sm text-slate-400">{loadMoreError}</p>
          <button
            type="button"
            onClick={() => { setLoadMoreError(null); handleLoadMore("manual"); }}
            className="rounded-full border border-white/20 bg-white/5 px-4 py-2 text-sm text-white transition hover:border-white/40 hover:bg-white/10 cursor-pointer"
          >
            Try again
          </button>
        </div>
      ) : null}
  </section>
);
}
