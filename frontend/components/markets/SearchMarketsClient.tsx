"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api-types";
import { FeaturedMarketsClient } from "@/components/markets/FeaturedMarketsClient";
import { loadFeaturedMarketsAction } from "@/app/actions/markets";
import { DEFAULT_PAGE_SIZE, DEFAULT_MAX_ITEMS } from "@/components/markets/constants";
import type { MarketSortOption } from "@/lib/markets";

type Props = {
  initialQuery?: string;
  initialResults: MarketSummary[];
  pageSize?: number;
  sortBy?: MarketSortOption;
};

type CacheEntry = {
  data: MarketSummary[];
  cachedAt: number;
};

const MIN_QUERY_LENGTH = 2;

export function SearchMarketsClient({
  initialQuery = "",
  initialResults,
  pageSize = DEFAULT_PAGE_SIZE,
  sortBy = "totalVolume",
}: Props) {
  const [query, setQuery] = useState(initialQuery);
  const [activeQuery, setActiveQuery] = useState(initialQuery.trim());
  const [seedResults, setSeedResults] = useState<MarketSummary[]>(initialResults);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isPending, startTransition] = useTransition();
  const cacheRef = useRef<Map<string, CacheEntry>>(new Map());
  const orderBy = "volume";

  useEffect(() => {
    const trimmed = initialQuery.trim();
    if (trimmed && initialResults.length) {
      cacheRef.current.set(trimmed, { data: initialResults, cachedAt: Date.now() });
    }
  }, [initialQuery, initialResults]);

  const resetEmpty = useCallback(() => {
    setSeedResults([]);
    setActiveQuery("");
    setRefreshKey((key) => key + 1);
  }, []);

  const runSearch = useCallback(
    async (nextQuery: string) => {
      const trimmed = nextQuery.trim();
      if (trimmed.length < MIN_QUERY_LENGTH) {
        setError(`Enter at least ${MIN_QUERY_LENGTH} characters to search.`);
        resetEmpty();
        return;
      }
      setError(null);
      const cached = cacheRef.current.get(trimmed);
      if (cached) {
        setActiveQuery(trimmed);
        setSeedResults(cached.data);
        setRefreshKey((key) => key + 1);
        return;
      }
      try {
        const data = await loadFeaturedMarketsAction(pageSize, { searchQuery: trimmed, status: "any", orderBy });
        cacheRef.current.set(trimmed, { data, cachedAt: Date.now() });
        setActiveQuery(trimmed);
        setSeedResults(data);
        setRefreshKey((key) => key + 1);
      } catch (err) {
        setError((err as Error).message || "Search failed. Please retry.");
      }
    },
    [pageSize, resetEmpty, orderBy],
  );

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      startTransition(() => {
        runSearch(query);
      });
    },
    [query, runSearch],
  );

  const effectiveStatus = activeQuery ? "any" : "active";
  const onlyActive = !activeQuery;
  const clientKey = useMemo(() => `${activeQuery}|${refreshKey}|${sortBy}`, [activeQuery, refreshKey, sortBy]);

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4 shadow-lg shadow-black/40">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Search markets</p>
        <h1 className="mt-2 text-3xl font-semibold text-white">Find a market</h1>
        <p className="mt-2 text-sm text-slate-400">
          Results are cached per query and include resolved/finalized markets. Active markets stay prioritized on the homepage and category pages.
        </p>
        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3 sm:flex-row">
          <label className="flex-1">
            <span className="sr-only">Search</span>
            <input
              type="search"
              placeholder="Search by keyword (e.g., election, BTC, sports)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full rounded-2xl border border-white/10 bg-slate-900/70 px-4 py-3 text-white outline-none transition focus:border-emerald-400"
            />
          </label>
          <button
            type="submit"
            disabled={isPending}
            className="rounded-2xl bg-brand-500 px-5 py-3 text-sm font-semibold uppercase tracking-[0.35em] text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isPending ? "Searching…" : "Search"}
          </button>
        </form>
        {error ? <p className="mt-2 text-sm text-rose-300">{error}</p> : null}
        {!error && activeQuery ? (
          <p className="mt-2 text-xs uppercase tracking-[0.3em] text-slate-500">
            Showing results for “{activeQuery}”
          </p>
        ) : null}
      </div>

      <FeaturedMarketsClient
        key={clientKey}
        initialMarkets={seedResults}
        pageSize={pageSize}
        maxItems={DEFAULT_MAX_ITEMS}
        searchQuery={activeQuery || undefined}
        emptyNotice={activeQuery ? "No markets matched your search." : "Start typing to see markets."}
        status={effectiveStatus}
        onlyActive={onlyActive}
        sortBy={sortBy}
      />
    </div>
  );
}
