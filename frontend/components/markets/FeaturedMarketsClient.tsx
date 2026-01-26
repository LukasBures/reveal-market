"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import type { EventSummary } from "@/lib/api-types";
import { EventGrid } from "@/components/events/EventGrid";
import { Skeleton } from "../ui/Skeleton";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "./constants";
import { logger } from "@/lib/logging";
import { fetchFeaturedEvents } from "@/lib/api";
import { categorySlugFromLabel } from "@/lib/slugs";
import type { MarketSortOption } from "@/lib/markets";

/**
 * We auto-load up to five batches via IntersectionObserver to give users a lazy-loading feel
 * before they need to press the button. After that the CTA becomes the explicit interaction.
 */
export const AUTO_LOAD_BATCHES = 5;

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
  const [intersectionSupported, setIntersectionSupported] = useState(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const setSentinel = useCallback((node: HTMLDivElement | null) => {
    sentinelRef.current = node;
  }, []);

  const batchSize = Math.max(pageSize, 30);
  const orderBy = "volume";
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
    queryFn: ({ pageParam = 0 }) =>
      fetchFeaturedEvents(batchSize, {
        searchQuery,
        category: normalizedCategory,
        offset: pageParam,
        status,
        trending,
        coalesceGroups: false,
        orderBy,
        closesWithinHours,
      }),
    initialPageParam: 0,
    initialData: {
      pages: [initialMarkets],
      pageParams: [0],
    },
    getNextPageParam: (lastPage, allPages) => {
      const total = allPages.reduce((acc, page) => acc + page.length, 0);
      if (total >= maxItems) return undefined;
      if (lastPage.length === 0) return undefined;
      return total;
    },
    staleTime: 30_000,
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
      setShowLoadingState(true);
      startTransition(() => {
        fetchNextPage()
          .then(() => {
            if (mode === "auto") {
              setAutoLoadCount((count) => count + 1);
            }
          })
          .catch((error) => {
            logger.clientError("FeaturedEventsClient:loadMore_failed", { error: (error as Error).message });
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
  const canAutoLoad = intersectionSupported && hasNextPage && autoLoadCount < AUTO_LOAD_BATCHES;
  const showManualButton = events.length > 0 && hasNextPage;
  const showLoadingIndicator =
    showLoadingState && intersectionSupported && autoLoadCount < AUTO_LOAD_BATCHES;

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
  }, [canAutoLoad, handleLoadMore, isBusy, events.length]);

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
          {isBusy ? "Loading..." : hasNextPage ? "Load more events" : "All events loaded"}
        </button>
      </div>
    )}
  </section>
);
}
