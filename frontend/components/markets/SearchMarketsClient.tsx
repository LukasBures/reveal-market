"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import type { EventSummary } from "@/lib/api-types";
import { FeaturedEventsClient } from "@/components/markets/FeaturedMarketsClient";
import { loadFeaturedEventsAction } from "@/app/actions/events";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "@/components/markets/constants";
import { MARKET_CATEGORY_FILTERS } from "@/lib/markets";
import type { MarketSortOption } from "@/lib/markets";
import { categorySlugFromLabel } from "@/lib/slugs";

type Props = {
  initialQuery?: string;
  initialCategory?: string | null;
  initialStatus?: string;
  initialResults: EventSummary[];
  pageSize?: number;
  sortBy?: MarketSortOption;
};

type CacheEntry = {
  data: EventSummary[];
  cachedAt: number;
};

const MIN_QUERY_LENGTH = 2;
const RECENT_SEARCHES_KEY = "rm_recent_searches";
const RECENT_SEARCHES_LIMIT = 6;
const STATUS_FILTERS = [
  { value: "any", label: "All" },
  { value: "active", label: "Active" },
  { value: "locked", label: "Locked" },
  { value: "settled", label: "Settled" },
  { value: "cancelled", label: "Cancelled" },
] as const;

type StatusFilter = (typeof STATUS_FILTERS)[number]["value"];

const isStatusFilter = (value: string): value is StatusFilter =>
  STATUS_FILTERS.some((status) => status.value === value);

const normalizeStatusFilter = (value?: string, fallback?: StatusFilter): StatusFilter => {
  const normalized = (value ?? "").toLowerCase();
  if (isStatusFilter(normalized)) {
    return normalized;
  }
  return fallback ?? "active";
};

const isEditableTarget = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  return Boolean(target.isContentEditable);
};

export function SearchEventsClient({
  initialQuery = "",
  initialCategory = null,
  initialStatus,
  initialResults,
  pageSize = DEFAULT_PAGE_SIZE,
  sortBy = "totalVolume",
}: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(initialQuery);
  const [activeQuery, setActiveQuery] = useState(initialQuery.trim());
  const [categoryFilter, setCategoryFilter] = useState<string | null>(initialCategory);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(
    normalizeStatusFilter(initialStatus, initialQuery.trim() ? "any" : "active"),
  );
  const [seedResults, setSeedResults] = useState<EventSummary[]>(initialResults);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isPending, startTransition] = useTransition();
  const cacheRef = useRef<Map<string, CacheEntry>>(new Map());
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const filtersInitializedRef = useRef(false);
  const statusTouchedRef = useRef(false);
  const queryRef = useRef(query);
  const skipFilterRefreshRef = useRef(false);
  const orderBy = "volume";

  const buildCacheKey = useCallback(
    (queryValue: string, categoryValue: string | null, statusValue: StatusFilter) =>
      `${queryValue.toLowerCase()}|${(categoryValue ?? "all").toLowerCase()}|${statusValue}`,
    [],
  );

  const updateUrlParams = useCallback(
    (
      next: { query: string; category: string | null; status: StatusFilter },
      mode: "replace" | "push" = "replace",
    ) => {
      const params = new URLSearchParams(searchParams?.toString() ?? "");
      if (next.query) {
        params.set("q", next.query);
      } else {
        params.delete("q");
      }
      if (next.category) {
        const slug = categorySlugFromLabel(next.category) ?? next.category;
        params.set("category", slug);
      } else {
        params.delete("category");
      }
      if (next.status && next.status !== "active") {
        params.set("status", next.status);
      } else {
        params.delete("status");
      }
      const queryString = params.toString();
      const nextUrl = (queryString ? `/search?${queryString}` : "/search") as Route;
      if (mode === "push") {
        router.push(nextUrl);
      } else {
        router.replace(nextUrl);
      }
    },
    [router, searchParams],
  );

  const persistRecentSearches = useCallback((next: string[]) => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(next));
    } catch {
      // ignore persistence issues
    }
  }, []);

  const addRecentSearch = useCallback(
    (term: string) => {
      const trimmed = term.trim();
      if (!trimmed) return;
      setRecentSearches((prev) => {
        const normalized = trimmed.toLowerCase();
        const next = [trimmed, ...prev.filter((item) => item.toLowerCase() !== normalized)].slice(
          0,
          RECENT_SEARCHES_LIMIT,
        );
        persistRecentSearches(next);
        return next;
      });
    },
    [persistRecentSearches],
  );

  const clearRecentSearches = useCallback(() => {
    setRecentSearches([]);
    if (typeof window === "undefined") return;
    try {
      window.localStorage.removeItem(RECENT_SEARCHES_KEY);
    } catch {
      // ignore persistence issues
    }
  }, []);

  useEffect(() => {
    const trimmed = initialQuery.trim();
    const effectiveQuery = trimmed.length >= MIN_QUERY_LENGTH ? trimmed : "";
    if (initialResults.length) {
      cacheRef.current.set(buildCacheKey(effectiveQuery, initialCategory, statusFilter), {
        data: initialResults,
        cachedAt: Date.now(),
      });
    }
  }, [buildCacheKey, initialCategory, initialQuery, initialResults, statusFilter]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = window.localStorage.getItem(RECENT_SEARCHES_KEY);
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        const cleaned = parsed.filter((item) => typeof item === "string" && item.trim().length > 0);
        setRecentSearches(cleaned.slice(0, RECENT_SEARCHES_LIMIT));
      }
    } catch {
      // ignore malformed storage
    }
  }, []);

  useEffect(() => {
    queryRef.current = query;
  }, [query]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.key === "/") {
        event.preventDefault();
        inputRef.current?.focus();
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const resetEmpty = useCallback(() => {
    setSeedResults([]);
    setActiveQuery("");
    setRefreshKey((key) => key + 1);
  }, []);

  const runSearch = useCallback(
    async (
      nextQuery: string,
      options?: {
        allowShortQuery?: boolean;
        updateMode?: "replace" | "push";
        category?: string | null;
        status?: StatusFilter;
      },
    ) => {
      const trimmed = nextQuery.trim();
      const allowShortQuery = options?.allowShortQuery ?? false;
      const nextCategory = options?.category ?? categoryFilter;
      const nextStatus = options?.status ?? statusFilter;
      const queryTooShort = trimmed.length > 0 && trimmed.length < MIN_QUERY_LENGTH;
      if (queryTooShort && !allowShortQuery) {
        setError(`Enter at least ${MIN_QUERY_LENGTH} characters to search.`);
        resetEmpty();
        return;
      }
      const effectiveQuery = trimmed.length >= MIN_QUERY_LENGTH ? trimmed : "";
      setError(null);
      const cacheKey = buildCacheKey(effectiveQuery, nextCategory, nextStatus);
      const cached = cacheRef.current.get(cacheKey);
      if (cached) {
        setActiveQuery(effectiveQuery);
        setSeedResults(cached.data);
        setRefreshKey((key) => key + 1);
        updateUrlParams(
          { query: effectiveQuery, category: nextCategory, status: nextStatus },
          options?.updateMode ?? "replace",
        );
        return;
      }
      try {
        const { data } = await loadFeaturedEventsAction(pageSize, {
          searchQuery: effectiveQuery || undefined,
          status: nextStatus,
          category: nextCategory ?? undefined,
          orderBy,
        });
        cacheRef.current.set(cacheKey, { data, cachedAt: Date.now() });
        setActiveQuery(effectiveQuery);
        setSeedResults(data);
        setRefreshKey((key) => key + 1);
        if (effectiveQuery) {
          addRecentSearch(effectiveQuery);
        }
        updateUrlParams(
          { query: effectiveQuery, category: nextCategory, status: nextStatus },
          options?.updateMode ?? "replace",
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed. Please retry.");
      }
    },
    [
      addRecentSearch,
      buildCacheKey,
      categoryFilter,
      orderBy,
      pageSize,
      resetEmpty,
      statusFilter,
      updateUrlParams,
    ],
  );

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const normalizedQuery = query.trim();
      const nextStatus =
        normalizedQuery.length >= MIN_QUERY_LENGTH && !statusTouchedRef.current ? "any" : statusFilter;
      if (nextStatus !== statusFilter) {
        skipFilterRefreshRef.current = true;
        setStatusFilter(nextStatus);
      }
      startTransition(() => {
        void runSearch(query, { updateMode: "push", status: nextStatus });
      });
    },
    [query, runSearch, statusFilter],
  );

  useEffect(() => {
    if (!filtersInitializedRef.current) {
      filtersInitializedRef.current = true;
      return;
    }
    if (skipFilterRefreshRef.current) {
      skipFilterRefreshRef.current = false;
      return;
    }
    startTransition(() => {
      void runSearch(queryRef.current, { allowShortQuery: true, updateMode: "replace" });
    });
  }, [categoryFilter, statusFilter, runSearch]);

  const onlyActive = statusFilter === "active";
  const hasActiveFilters = Boolean(activeQuery) || Boolean(categoryFilter) || statusFilter !== "active";
  const emptyNotice = activeQuery
    ? "No events matched your search."
    : hasActiveFilters
      ? "No events matched your filters."
      : "Start typing to see events.";
  const clientKey = useMemo(
    () => `${activeQuery}|${categoryFilter ?? "all"}|${statusFilter}|${refreshKey}|${sortBy}`,
    [activeQuery, categoryFilter, refreshKey, sortBy, statusFilter],
  );

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4 shadow-lg shadow-black/40">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Search events</p>
        <h2 className="mt-2 text-3xl font-semibold text-white">Find an event</h2>
        <p className="mt-2 text-sm text-slate-400">
          Results are cached per query and include resolved/finalized events. Active events stay prioritized on the homepage and category pages.
        </p>
        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label className="flex-1">
            <span className="sr-only">Search</span>
            <input
              type="search"
              name="eventsSearch"
              placeholder="Search by keyword (e.g., election, BTC, sports)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              ref={inputRef}
              className="w-full rounded-2xl border border-white/10 bg-slate-900/70 px-4 py-3 text-white outline-none transition focus:border-emerald-400"
            />
          </label>
          <button
            type="submit"
            disabled={isPending}
            className="w-full rounded-2xl bg-brand-500 px-5 py-3 text-sm font-semibold uppercase tracking-[0.2em] text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto sm:tracking-[0.35em]"
          >
            {isPending ? "Searching..." : "Search"}
          </button>
        </form>
        {error ? <p className="mt-2 text-sm text-rose-300">{error}</p> : null}
        {!error && activeQuery ? (
          <p className="mt-2 text-xs uppercase tracking-[0.3em] text-slate-500">
            Showing results for “{activeQuery}”
          </p>
        ) : null}
        <div className="mt-4 space-y-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500">Category</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setCategoryFilter(null)}
                className={`rounded-full px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.2em] transition sm:py-1 ${
                  !categoryFilter ? "bg-white text-slate-900" : "bg-white/10 text-white/80 hover:bg-white/20"
                }`}
              >
                All
              </button>
              {MARKET_CATEGORY_FILTERS.map((category) => (
                <button
                  key={category}
                  type="button"
                  onClick={() => setCategoryFilter(category)}
                  className={`rounded-full px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.2em] transition sm:py-1 ${
                    categoryFilter === category
                      ? "bg-brand-400 text-slate-900"
                      : "bg-white/10 text-white/80 hover:bg-white/20"
                  }`}
                >
                  {category}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-[0.3em] text-slate-500">Status</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {STATUS_FILTERS.map((status) => (
                <button
                  key={status.value}
                  type="button"
                  onClick={() => {
                    statusTouchedRef.current = true;
                    setStatusFilter(status.value);
                  }}
                  className={`rounded-full px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.2em] transition sm:py-1 ${
                    statusFilter === status.value
                      ? "bg-white text-slate-900"
                      : "bg-white/10 text-white/80 hover:bg-white/20"
                  }`}
                >
                  {status.label}
                </button>
              ))}
            </div>
          </div>
          {recentSearches.length > 0 && (
            <div>
              <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.3em] text-slate-500">
                <span>Recent searches</span>
                <button
                  type="button"
                  onClick={clearRecentSearches}
                  className="text-[10px] font-semibold uppercase tracking-[0.3em] text-slate-400 transition hover:text-white"
                >
                  Clear
                </button>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {recentSearches.map((term) => (
                  <button
                    key={term}
                    type="button"
                    onClick={() => {
                      setQuery(term);
                      startTransition(() => {
                        void runSearch(term, { updateMode: "push" });
                      });
                    }}
                    className="rounded-full bg-white/10 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/80 transition hover:bg-white/20 sm:py-1"
                  >
                    {term}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <FeaturedEventsClient
        key={clientKey}
        initialMarkets={seedResults}
        pageSize={pageSize}
        maxItems={DEFAULT_MAX_ITEMS}
        searchQuery={activeQuery || undefined}
        categoryFilter={categoryFilter || undefined}
        emptyNotice={emptyNotice}
        status={statusFilter}
        onlyActive={onlyActive}
        sortBy={sortBy}
      />
    </div>
  );
}
