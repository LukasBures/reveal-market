"use client";

import Link from "next/link";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api";
import { categorySlugFromLabel } from "@/lib/slugs";

const categories = [
  "Trending",
  "Politics",
  "Sports",
  "Finance",
  "Crypto",
  "Geopolitics",
  "AI & Tech",
];

type Props = {
  initialSearch?: string;
};

export function MarketFilters({ initialSearch }: Props) {
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
      return;
    }
    const controller = new AbortController();
    fetchAbortRef.current = controller;
    const debounce = setTimeout(async () => {
      try {
        setLoadingSuggestions(true);
        const response = await fetch(`/markets/suggest?q=${encodeURIComponent(trimmed)}&limit=5`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) {
          setSuggestions([]);
          return;
        }
        const payload = await response.json();
        const mapToSummary = (item: any): MarketSummary => ({
          eventId: item.event_id ?? item.eventId ?? "unknown",
          title: item.title ?? "Untitled market",
          category: item.category ?? item.tags?.[0] ?? "General",
          tags: item.tags ?? [],
          status: item.status ?? undefined,
          commitDeadline: item.commit_deadline ?? item.commitDeadline ?? undefined,
          revealDeadline: item.reveal_deadline ?? item.revealDeadline ?? undefined,
          liquidityUsd: item.extra_data?.liquidityUsd ?? item.liquidity_usd,
          outcomes: item.outcomes ?? [],
          outcomePrices: item.outcome_prices ?? [],
          imageUrl: item.image_url ?? null,
        });
        const dedupeSummaries = (items: MarketSummary[]) => {
          const seen = new Set<string>();
          return items.filter((entry) => {
            if (!entry.eventId || seen.has(entry.eventId)) {
              return false;
            }
            seen.add(entry.eventId);
            return true;
          });
        };

        let deduped: MarketSummary[] = [];
        if (Array.isArray(payload)) {
          deduped = dedupeSummaries(payload.map(mapToSummary));
        }

        if (!deduped.length) {
          const fallbackResponse = await fetch(
            `/markets?limit=5&search=${encodeURIComponent(trimmed)}`,
            { signal: controller.signal, cache: "no-store" },
          );
          if (fallbackResponse.ok) {
            const fallbackPayload = await fallbackResponse.json();
            const list = Array.isArray(fallbackPayload)
              ? fallbackPayload
              : Array.isArray(fallbackPayload?.items)
                ? fallbackPayload.items
                : [];
            deduped = dedupeSummaries(list.map(mapToSummary));
          }
        }

        setSuggestions(deduped);
        setHighlightedIndex(deduped.length ? 0 : -1);
        setSuggestionsVisible(true);
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
  }, [deferredSearch]);

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

  return (
    <section className="glass-panel relative overflow-hidden px-4 py-8 shadow-2xl shadow-black/40 sm:px-6 md:px-10">
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
          <div className="flex flex-wrap justify-center gap-4 text-xs uppercase tracking-[0.4em] text-slate-500 lg:justify-start">
            <span className="text-white/80">
              ≈ <strong className="text-white">120</strong> live markets
            </span>
            <span className="text-white/80">
              SLA <strong className="text-white">30s</strong> settlement
            </span>
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
                    <div className="h-10 w-10 flex-shrink-0 overflow-hidden rounded-lg border border-white/10">
                      <div
                        className={`h-full w-full ${
                          suggestion.imageUrl ? "" : "bg-gradient-to-br from-brand-500/20 via-slate-900 to-slate-950"
                        }`}
                        style={
                          suggestion.imageUrl
                            ? {
                                backgroundImage: `url(${suggestion.imageUrl})`,
                                backgroundSize: "cover",
                                backgroundPosition: "center",
                              }
                            : undefined
                        }
                        aria-hidden="true"
                      />
                    </div>
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
              <span className="text-xs uppercase tracking-[0.4em] text-slate-400">#{slug}</span>
              <span className="ml-2 font-semibold">{category}</span>
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
