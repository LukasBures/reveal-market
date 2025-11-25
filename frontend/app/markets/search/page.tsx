"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { fetchFeaturedMarkets } from "@/lib/api";
import type { MarketSummary } from "@/lib/api-types";

const PAGE_SIZE = 12;

export default function MarketsSearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MarketSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const hasMore = results.length === PAGE_SIZE * (page + 1);

  useEffect(() => {
    let cancelled = false;
    async function runSearch() {
      if (!query || query.trim().length < 2) {
        setResults([]);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const data = await fetchFeaturedMarkets(PAGE_SIZE, { searchQuery: query, offset: page * PAGE_SIZE });
        if (!cancelled) setResults(data);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    runSearch();
    return () => {
      cancelled = true;
    };
  }, [query, page]);

  const pagedLabel = useMemo(() => {
    const start = page * PAGE_SIZE + 1;
    const end = page * PAGE_SIZE + results.length;
    return results.length ? `Showing ${start}–${end}` : "No results yet";
  }, [page, results.length]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-950 to-black px-4 py-10 text-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <div className="flex flex-col gap-2">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Search markets</p>
          <h1 className="text-3xl font-semibold text-white">Find a market</h1>
          <p className="text-sm text-slate-400">
            Results are fetched from the live API (no mock data). Enter at least two characters to search titles and
            tags.
          </p>
          <input
            className="mt-2 w-full rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-white outline-none transition focus:border-emerald-400"
            placeholder="Search by keyword (e.g., election, BTC, sports)"
            value={query}
            onChange={(e) => {
              setPage(0);
              setQuery(e.target.value);
            }}
          />
        </div>

        <div className="flex items-center justify-between text-sm text-slate-400">
          <span>{pagedLabel}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className={`rounded-full px-3 py-1 text-xs uppercase tracking-[0.2em] ${
                page === 0 ? "bg-white/10 text-white/40" : "bg-white/15 text-white hover:bg-white/25"
              }`}
            >
              Prev
            </button>
            <button
              type="button"
              disabled={!hasMore}
              onClick={() => setPage((p) => p + 1)}
              className={`rounded-full px-3 py-1 text-xs uppercase tracking-[0.2em] ${
                !hasMore ? "bg-white/10 text-white/40" : "bg-white/15 text-white hover:bg-white/25"
              }`}
            >
              Next
            </button>
          </div>
        </div>

        {error && <p className="text-rose-300 text-sm">Search failed: {error}</p>}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {results.map((market) => (
            <Link
              key={market.eventId}
              href={`/markets/${market.eventId}`}
              className="group rounded-3xl border border-white/10 bg-slate-900/60 p-4 transition hover:border-emerald-400/60"
            >
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{market.category || "Market"}</p>
              <h3 className="mt-2 text-lg font-semibold text-white group-hover:text-emerald-200">{market.title}</h3>
              {market.tags && (
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-400">
                  {market.tags.slice(0, 4).map((tag) => (
                    <span key={tag} className="rounded-full bg-white/10 px-2 py-1">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              <div className="mt-3 text-sm text-slate-400">
                Status: <span className="text-white">{market.status || "commit"}</span>
              </div>
            </Link>
          ))}
        </div>

        {loading && <p className="text-sm text-slate-400">Loading results…</p>}
        {!loading && results.length === 0 && query.trim().length >= 2 && (
          <p className="text-sm text-slate-400">No markets match “{query}”.</p>
        )}
      </div>
    </div>
  );
}
