"use client";

import Link from "next/link";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api-types";
import { categorySlugFromLabel } from "@/lib/slugs";
import { MarketArtwork } from "@/components/markets/MarketArtwork";
import { mapApiMarketToSummary } from "@/lib/marketMapper";
import { formatNumber } from "@/lib/formatters";

const categories = [
  "Trending",
  "Politics",
  "Sports",
  "Finance",
  "Crypto",
  "Geopolitics",
  "Tech",
];

type Props = {
  initialSearch?: string;
  liveMarketsCount?: number;
  finalizedMarketsCount?: number;
  totalMarketsCount?: number;
};

const SUGGESTION_CACHE_LIMIT = 50;
const SUGGESTION_CACHE_TTL_MS = 60_000;
const windowSuggestionCache = new Map<
  string,
  { data: MarketSummary[]; expiresAt: number }
>();

export function MarketFilters({ initialSearch, liveMarketsCount, finalizedMarketsCount, totalMarketsCount }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const [search, setSearch] = useState(initialSearch ?? "");
  const deferredSearch = useDeferredValue(search);
  const [isPending, startTransition] = useTransition();
  const [suggestions, setSuggestions] = useState<MarketSummary[]>([]);
  const [suggestionsVisible, setSuggestionsVisible] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState<number>(-1);
  const fetchAbortRef = useRef<AbortController | null>(null);
  const hideTimeout = useRef<NodeJS.Timeout | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const heroStats = useMemo(
    () => [
      {
        label: "Live markets",
        value:
          typeof liveMarketsCount === "number" && liveMarketsCount > 0
            ? formatNumber(liveMarketsCount)
            : "—",
      },
      {
        label: "Finalized markets",
        value:
          typeof finalizedMarketsCount === "number" && finalizedMarketsCount > 0
            ? formatNumber(finalizedMarketsCount)
            : "—",
      },
      {
        label: "Total markets tracked",
        value:
          typeof totalMarketsCount === "number" && totalMarketsCount > 0
            ? formatNumber(totalMarketsCount)
            : "—",
      },
    ],
    [liveMarketsCount, finalizedMarketsCount, totalMarketsCount],
  );

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    startTransition(() => {
      const query = search.trim();
      const next = new URLSearchParams(params?.toString() ?? "");
      if (query) {
        next.set("q", query);
      } else {
        next.delete("q");
      }
      router.push(next.toString() ? `/?${next.toString()}` : "/");
    });
  };

  useEffect(() => {
    if (hideTimeout.current) {
      clearTimeout(hideTimeout.current);
      hideTimeout.current = null;
    }
    if (fetchAbortRef.current) {
      fetchAbortRef.current.abort();
      fetchAbortRef.current = null;
    }
    const trimmed = deferredSearch.trim();
    if (trimmed.length < 2 || new Set(trimmed).size === 1) {
      setSuggestions([]);
      setSuggestionsVisible(false);
      setHighlightedIndex(-1);
      setLoadingSuggestions(false);
      return;
    }
    const cacheKey = `${trimmed.toLowerCase()}|5`;
    const cache = windowSuggestionCache;
    const controller = new AbortController();
    fetchAbortRef.current = controller;
    if (!loadingSuggestions) {
      setLoadingSuggestions(true);
    }
    const cachedEntry = cache.get(cacheKey);
    if (cachedEntry && cachedEntry.expiresAt > Date.now()) {
      setSuggestions(cachedEntry.data);
      setHighlightedIndex(cachedEntry.data.length ? 0 : -1);
      setLoadingSuggestions(false);
      fetchAbortRef.current = null;
      return;
    }
    if (cachedEntry) {
      cache.delete(cacheKey);
    }
    const debounce = setTimeout(async () => {
      try {
        const params = new URLSearchParams();
        params.set("limit", "5");
        params.set("q", trimmed);
        const timeoutId = setTimeout(() => controller.abort(), 2000);
        const response = await fetch(`/api/markets/suggest?${params.toString()}`, {
          signal: controller.signal,
          headers: {
            Accept: "application/json",
          },
        });
        clearTimeout(timeoutId);
        if (!response.ok) {
          throw new Error(`suggestions failed (${response.status})`);
        }
        const payload = await response.json();
        const results = Array.isArray(payload) ? payload.map(mapApiMarketToSummary) : [];
        cache.set(cacheKey, { data: results, expiresAt: Date.now() + SUGGESTION_CACHE_TTL_MS });
        if (cache.size > SUGGESTION_CACHE_LIMIT) {
          const keys = Array.from(cache.keys());
          for (const key of keys.slice(0, cache.size - SUGGESTION_CACHE_LIMIT)) {
            cache.delete(key);
          }
        }
        setSuggestions(results);
        setHighlightedIndex(results.length ? 0 : -1);
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          console.error("Failed to fetch suggestions", error);
        }
      } finally {
        setLoadingSuggestions(false);
        if (fetchAbortRef.current === controller) {
          fetchAbortRef.current = null;
        }
      }
    }, 200);
    return () => {
      clearTimeout(debounce);
      controller.abort();
      if (fetchAbortRef.current === controller) {
        fetchAbortRef.current = null;
      }
    };
  }, [deferredSearch, loadingSuggestions]);

  const hideSuggestionsWithDelay = () => {
    hideTimeout.current = setTimeout(() => {
      setSuggestionsVisible(false);
      setHighlightedIndex(-1);
    }, 150);
  };

  const handleKeyboardNavigation = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (!suggestionsVisible || suggestions.length === 0) {
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setHighlightedIndex((prev) => {
          const next = prev + 1;
          return next >= suggestions.length ? 0 : next;
        });
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlightedIndex((prev) => {
          if (prev <= 0) {
            return suggestions.length - 1;
          }
          return prev - 1;
        });
      } else if (event.key === "Tab") {
        event.preventDefault();
        setHighlightedIndex((prev) => {
          const next = prev + 1;
          return next >= suggestions.length ? 0 : next;
        });
      } else if (event.key === "Enter") {
        if (highlightedIndex >= 0 && highlightedIndex < suggestions.length) {
          event.preventDefault();
          router.push(`/markets/${suggestions[highlightedIndex].eventId}`);
          setSuggestionsVisible(false);
        }
      }
    },
    [highlightedIndex, suggestions, suggestionsVisible, router],
  );

  useEffect(() => {
    categories.slice(0, 4).forEach((category) => {
      const slug = categorySlugFromLabel(category);
      if (!slug) return;
      const path = `/categories/${encodeURIComponent(slug)}` as Route;
      router.prefetch(path);
    });
  }, [router]);

  useEffect(() => {
    const trimmed = search.trim();
    setSuggestionsVisible(trimmed.length >= 2 && (loadingSuggestions || suggestions.length > 0));
  }, [suggestions, loadingSuggestions, search]);

  return (
    <section className="glass-panel relative overflow-visible px-4 py-8 shadow-2xl shadow-black/40 sm:px-6 md:px-10">
      <div className="pointer-events-none absolute -top-24 right-0 h-64 w-64 rounded-full bg-brand-400/20 blur-3xl" />
      <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-4 text-center lg:max-w-2xl lg:text-left">
          <p className="text-xs uppercase tracking-[0.4em] text-slate-400">Explore</p>
          <div>
            <h1 className="text-3xl font-semibold text-white sm:text-4xl">Trade-ready markets curated for every narrative.</h1>
            <p className="mt-3 text-base text-slate-300">
              Browse liquidity-backed order books, trending catalysts, and bespoke categories powered by the Reveal Market feed.
              Search instantly or jump straight into a category.
            </p>
          </div>
          <div className="flex flex-wrap justify-center gap-4 text-xs uppercase tracking-[0.35em] text-slate-500 lg:justify-start">
            {heroStats.map((stat) => (
              <span key={stat.label} className="text-white/80">
                {stat.label}: <strong className="text-white">{stat.value}</strong>
              </span>
            ))}
          </div>
        </div>
        <form onSubmit={handleSubmit} aria-label="Search markets" className="relative w-full max-w-xl">
          <div className="rounded-2xl border border-white/10 bg-slate-950/60 px-4 py-3 shadow-inner shadow-black/30">
            <label htmlFor="market-search" className="sr-only">
              Search markets
            </label>
            <input
              id="market-search"
              type="search"
              placeholder="Search markets, oracles, or narratives"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onFocus={() => search.trim().length >= 2 && setSuggestionsVisible(true)}
              onBlur={hideSuggestionsWithDelay}
              onKeyDown={handleKeyboardNavigation}
              ref={inputRef}
              className="w-full bg-transparent text-base text-white placeholder:text-slate-500 focus:outline-none"
              autoComplete="off"
            />
          </div>
          <button
            type="submit"
            disabled={isPending}
            className="absolute right-4 top-1/2 -translate-y-1/2 rounded-full bg-brand-500 px-3 py-1 text-xs font-semibold uppercase tracking-[0.35em] text-white transition hover:bg-brand-400 disabled:opacity-50 sm:px-4"
          >
            {isPending ? "…" : "Go"}
          </button>
          {suggestionsVisible && (
            <div
              className="fade-up absolute top-[calc(100%+0.75rem)] z-20 w-full overflow-hidden rounded-2xl border border-white/10 bg-slate-900/95 shadow-2xl shadow-black/60"
              role="listbox"
              aria-live="polite"
            >
              {loadingSuggestions && <p className="px-4 py-3 text-sm text-slate-400">Searching…</p>}
              {!loadingSuggestions && suggestions.length === 0 && (
                <p className="px-4 py-3 text-sm text-slate-400">No matches yet</p>
              )}
              {!loadingSuggestions &&
                suggestions.map((suggestion, index) => (
                  <button
                    key={suggestion.eventId}
                    type="button"
                    role="option"
                    aria-selected={index === highlightedIndex}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      router.push(`/markets/${suggestion.eventId}`);
                      setSuggestionsVisible(false);
                    }}
                    className={`flex w-full items-center gap-3 px-4 py-3 text-left text-sm transition ${
                      index === highlightedIndex ? "bg-white/10" : "hover:bg-white/5"
                    }`}
                  >
                  <MarketArtwork
                    src={suggestion.imageUrl ?? null}
                    alt={`${suggestion.title} artwork`}
                    sizeClass="w-10"
                    roundedClass="rounded-lg"
                    borderClass="border border-white/10"
                  />
                    <div className="flex flex-col">
                      <span className="font-semibold leading-snug text-white">{suggestion.title}</span>
                      <span className="text-[0.65rem] uppercase tracking-[0.4em] text-slate-500">
                        {suggestion.category ?? "General"}
                      </span>
                    </div>
                  </button>
                ))}
            </div>
          )}
        </form>
      </div>
      <div className="divider-gradient my-8" aria-hidden="true" />
      <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
        {categories.map((category) => {
          const slug = categorySlugFromLabel(category);
          if (!slug) return null;
          return (
            <Link
              key={category}
              href={`/categories/${encodeURIComponent(slug)}`}
              prefetch
              className="group rounded-full border border-white/10 bg-slate-900/30 px-4 py-2 text-sm text-slate-100 transition hover:border-brand-400/60 hover:text-white"
            >
              <span className="text-xs uppercase tracking-[0.4em] text-slate-400">{category}</span>
            </Link>
          );
        })}
      </div>
      <div className="mt-8 grid gap-4 rounded-2xl border border-white/10 bg-gradient-to-br from-white/5 to-transparent p-4 text-sm text-slate-300 md:grid-cols-2">
        <div>
          <p className="text-xs uppercase tracking-[0.4em] text-slate-500">UX tip</p>
          <p className="mt-2 text-slate-200">
            Keyboard <kbd className="rounded bg-white/10 px-1 py-0.5 text-[0.65rem]">↑/↓</kbd> navigates suggestions,
            while <kbd className="rounded bg-white/10 px-1 py-0.5 text-[0.65rem]">Enter</kbd> opens a market instantly.
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.4em] text-slate-500">Need a bespoke feed?</p>
          <p className="mt-2">
            Email{" "}
            <a href="mailto:hello@revealmarket.xyz" className="font-semibold text-brand-200 underline underline-offset-4">
              hello@revealmarket.xyz
            </a>{" "}
            for curation tiers, design support, and API priorities.
          </p>
        </div>
      </div>
    </section>
  );
}
