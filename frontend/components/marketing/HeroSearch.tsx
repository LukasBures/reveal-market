"use client";

import { useRouter } from "next/navigation";
import { useCallback, useDeferredValue, useEffect, useRef, useState, useTransition } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { mapApiMarketToSummary } from "@/lib/marketMapper";
import type { MarketSummary } from "@/lib/api-types";
import { MarketArtwork } from "@/components/markets/MarketArtwork";

const SUGGESTION_CACHE = new Map<string, { data: MarketSummary[]; expiresAt: number }>();
const CACHE_LIMIT = 50;
const CACHE_TTL_MS = 60_000;
const SUGGEST_TIMEOUT_MS = 8000;
const SUGGEST_RETRY_DELAY_MS = 400;

type Props = {
  initialSearch?: string;
};

export function HeroSearch({ initialSearch = "" }: Props) {
  const router = useRouter();
  const [search, setSearch] = useState(initialSearch);
  const deferredSearch = useDeferredValue(search);
  const [suggestions, setSuggestions] = useState<MarketSummary[]>([]);
  const [suggestionsVisible, setSuggestionsVisible] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const [isPending, startTransition] = useTransition();
  const fetchAbortRef = useRef<AbortController | null>(null);
  const hideTimeout = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!deferredSearch.trim() || deferredSearch.trim().length < 2) {
      setSuggestions([]);
      setHighlightedIndex(-1);
      return;
    }
    const trimmed = deferredSearch.trim();
    const cacheKey = `${trimmed.toLowerCase()}|hero`;
    const cached = SUGGESTION_CACHE.get(cacheKey);
    const controller = new AbortController();
    fetchAbortRef.current = controller;

    if (cached && cached.expiresAt > Date.now()) {
      setSuggestions(cached.data);
      setHighlightedIndex(cached.data.length ? 0 : -1);
      return;
    }
    if (cached) {
      SUGGESTION_CACHE.delete(cacheKey);
    }

    const timer = setTimeout(async () => {
      try {
        setLoadingSuggestions(true);
        const params = new URLSearchParams({ limit: "5", q: trimmed });
        const fetchSuggestions = async () => {
          const timeoutId = setTimeout(() => controller.abort(), SUGGEST_TIMEOUT_MS);
          try {
            const res = await fetch(`/api/events/suggest?${params.toString()}`, {
              signal: controller.signal,
              headers: { Accept: "application/json" },
            });
            if (!res.ok) {
              return [];
            }
            const payload = await res.json();
            return Array.isArray(payload) ? payload.map(mapApiMarketToSummary) : [];
          } finally {
            clearTimeout(timeoutId);
          }
        };
        let mapped = await fetchSuggestions();
        if (mapped.length === 0 && !controller.signal.aborted) {
          await new Promise((resolve) => setTimeout(resolve, SUGGEST_RETRY_DELAY_MS));
          if (!controller.signal.aborted) {
            mapped = await fetchSuggestions();
          }
        }
        SUGGESTION_CACHE.set(cacheKey, { data: mapped, expiresAt: Date.now() + CACHE_TTL_MS });
        if (SUGGESTION_CACHE.size > CACHE_LIMIT) {
          const keys = Array.from(SUGGESTION_CACHE.keys());
          for (const key of keys.slice(0, SUGGESTION_CACHE.size - CACHE_LIMIT)) {
            SUGGESTION_CACHE.delete(key);
          }
        }
        setSuggestions(mapped);
        setHighlightedIndex(mapped.length ? 0 : -1);
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          console.error("HeroSearch: failed to load suggestions", error);
        }
      } finally {
        setLoadingSuggestions(false);
        if (fetchAbortRef.current === controller) {
          fetchAbortRef.current = null;
        }
      }
    }, 200);

    return () => {
      clearTimeout(timer);
      controller.abort();
      if (fetchAbortRef.current === controller) {
        fetchAbortRef.current = null;
      }
    };
  }, [deferredSearch]);

  const hideSuggestionsWithDelay = () => {
    hideTimeout.current = setTimeout(() => {
      setSuggestionsVisible(false);
      setHighlightedIndex(-1);
    }, 150);
  };

  const handleKeyboardNavigation = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (!suggestionsVisible || suggestions.length === 0) return;
      if (event.key === "ArrowDown" || event.key === "Tab") {
        event.preventDefault();
        setHighlightedIndex((prev) => {
          const next = prev + 1;
          return next >= suggestions.length ? 0 : next;
        });
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setHighlightedIndex((prev) => (prev <= 0 ? suggestions.length - 1 : prev - 1));
      } else if (event.key === "Enter" && highlightedIndex >= 0 && highlightedIndex < suggestions.length) {
        event.preventDefault();
        router.push(`/events/${suggestions[highlightedIndex].groupSlug ?? suggestions[highlightedIndex].eventId}`);
        setSuggestionsVisible(false);
      }
    },
    [suggestionsVisible, suggestions, highlightedIndex, router],
  );

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = search.trim();
    if (highlightedIndex >= 0 && highlightedIndex < suggestions.length) {
      router.push(`/events/${suggestions[highlightedIndex].groupSlug ?? suggestions[highlightedIndex].eventId}`);
      return;
    }
    if (!query) return;
    startTransition(() => {
      const params = new URLSearchParams({ q: query });
      router.push(`/?${params.toString()}`);
    });
  };

  return (
    <form onSubmit={handleSubmit} aria-label="Search markets" className="relative w-full">
      <label htmlFor="hero-market-search" className="sr-only">
        Search markets
      </label>
      <div className="rounded-2xl border border-white/10 bg-slate-950/60 px-4 py-3 shadow-inner shadow-black/30">
        <input
          id="hero-market-search"
          type="search"
          placeholder="Search markets, oracles, or narratives"
          className="w-full bg-transparent text-base text-white placeholder:text-slate-500 focus:outline-none"
          autoComplete="off"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            if (e.target.value.trim().length >= 2) {
              setSuggestionsVisible(true);
            } else {
              setSuggestionsVisible(false);
            }
          }}
          onFocus={() => search.trim().length >= 2 && setSuggestionsVisible(true)}
          onBlur={hideSuggestionsWithDelay}
          onKeyDown={handleKeyboardNavigation}
        />
      </div>
      <button
        type="submit"
        disabled={isPending}
        className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full bg-brand-500 px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-white transition hover:bg-brand-400 disabled:opacity-50 sm:right-4 sm:px-5 sm:tracking-[0.35em]"
      >
        {isPending ? "..." : "Search"}
      </button>
      {suggestionsVisible && (
        <div
          className="fade-up absolute top-[calc(100%+0.75rem)] z-20 w-full overflow-hidden rounded-2xl border border-white/10 bg-slate-900/95 shadow-2xl shadow-black/60"
          role="listbox"
          aria-live="polite"
        >
          {loadingSuggestions && <p className="px-4 py-3 text-sm text-slate-400">Searching...</p>}
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
                  router.push(`/events/${suggestion.groupSlug ?? suggestion.eventId}`);
                  setSuggestionsVisible(false);
                }}
                className={`flex w-full min-w-0 items-center gap-3 px-4 py-3 text-left text-sm transition ${
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
                <div className="min-w-0 flex flex-col">
                  <span className="line-clamp-2 font-semibold leading-snug text-white">{suggestion.title}</span>
                  <span className="text-[0.65rem] uppercase tracking-[0.4em] text-slate-500">
                    {suggestion.category ?? "General"}
                  </span>
                </div>
              </button>
            ))}
        </div>
      )}
    </form>
  );
}
