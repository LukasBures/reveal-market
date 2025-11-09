"use client";

import Link from "next/link";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useRef, useState, useTransition } from "react";
import type { MarketSummary } from "@/lib/api";
import { categorySlugFromLabel, tagSlugFromLabel } from "@/lib/slugs";

const categories = [
  "Trending",
  "Politics",
  "Sports",
  "Finance",
  "Crypto",
  "Geopolitics",
  "AI & Tech",
];

const quickTags = [
  { label: "Gov shutdown", slug: "gov-shutdown" },
  { label: "Fed policy", slug: "fed-policy" },
  { label: "EU elections", slug: "eu-elections" },
  { label: "BTC halving", slug: "btc-halving" },
  { label: "AI regulation", slug: "ai-regulation" },
  { label: "Climate", slug: "climate" },
];

type Props = {
  initialSearch?: string;
};

export function MarketFilters({ initialSearch }: Props) {
  const router = useRouter();
  const params = useSearchParams();
  const [search, setSearch] = useState(initialSearch ?? "");
  const [isPending, startTransition] = useTransition();
  const [suggestions, setSuggestions] = useState<MarketSummary[]>([]);
  const [suggestionsVisible, setSuggestionsVisible] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const hideTimeout = useRef<NodeJS.Timeout | null>(null);

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
    const trimmed = search.trim();
    if (trimmed.length < 2) {
      setSuggestions([]);
      setSuggestionsVisible(false);
      return;
    }
    const controller = new AbortController();
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
        if (!Array.isArray(payload)) {
          setSuggestions([]);
          return;
        }
        const mapped: MarketSummary[] = payload.map((item: any) => ({
          eventId: item.event_id ?? item.eventId ?? "unknown",
          title: item.title ?? "Untitled market",
          category: item.category ?? item.tags?.[0] ?? "General",
          tags: item.tags ?? [],
          status: item.status ?? undefined,
          commitDeadline: item.commit_deadline ?? undefined,
          revealDeadline: item.reveal_deadline ?? undefined,
          liquidityUsd: item.extra_data?.liquidityUsd ?? item.liquidity_usd,
          outcomes: item.outcomes ?? [],
          outcomePrices: item.outcome_prices ?? [],
          imageUrl: item.image_url ?? null,
        }));
        setSuggestions(mapped);
        setSuggestionsVisible(true);
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          console.error("Failed to fetch suggestions", error);
        }
      } finally {
        setLoadingSuggestions(false);
      }
    }, 200);
    return () => {
      clearTimeout(debounce);
      controller.abort();
    };
  }, [search]);

  const hideSuggestionsWithDelay = () => {
    hideTimeout.current = setTimeout(() => {
      setSuggestionsVisible(false);
    }, 150);
  };

  useEffect(() => {
    categories.slice(0, 4).forEach((category) => {
      const slug = categorySlugFromLabel(category);
      if (!slug) return;
      const path = `/categories/${encodeURIComponent(slug)}` as Route;
      router.prefetch(path);
    });
    quickTags.slice(0, 4).forEach((tag) => {
      const path = `/tags/${encodeURIComponent(tag.slug)}` as Route;
      router.prefetch(path);
    });
  }, [router]);

  return (
    <section className="space-y-6 rounded-3xl border border-white/5 bg-slate-900/60 p-6 shadow-lg shadow-black/40">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Explore</p>
          <h1 className="text-3xl font-semibold text-white">Live markets across every narrative.</h1>
        </div>
        <form
          onSubmit={handleSubmit}
          className="relative w-full md:w-64"
        >
          <input
            type="search"
            placeholder="Search markets"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onFocus={() => search.trim().length >= 2 && setSuggestionsVisible(true)}
            onBlur={hideSuggestionsWithDelay}
            className="w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none ring-brand-400/50 focus:ring-2"
          />
          <button
            type="submit"
            disabled={isPending}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-brand-500 px-3 py-1 text-xs font-semibold text-white opacity-90 transition hover:bg-brand-400 disabled:opacity-50"
          >
            {isPending ? "…" : "Go"}
          </button>
          {suggestionsVisible && (
            <div className="absolute top-full z-20 mt-2 w-full rounded-2xl border border-white/10 bg-slate-900/90 text-sm text-white shadow-lg shadow-black/50">
              {loadingSuggestions && (
                <p className="px-4 py-3 text-slate-400">Searching…</p>
              )}
              {!loadingSuggestions && suggestions.length === 0 && (
                <p className="px-4 py-3 text-slate-400">No matches yet</p>
              )}
              {!loadingSuggestions &&
                suggestions.map((suggestion) => (
                  <button
                    key={suggestion.eventId}
                    type="button"
                    onMouseDown={(event) => {
                      event.preventDefault();
                      router.push(`/markets/${suggestion.eventId}`);
                    }}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-white/10"
                  >
                    <div className="h-10 w-10 flex-shrink-0 overflow-hidden rounded-lg border border-white/10">
                      <div
                        className={`h-full w-full ${
                          suggestion.imageUrl ? "" : "bg-gradient-to-br from-brand-500/30 via-slate-900 to-slate-950"
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
                      <span className="line-clamp-1 font-semibold">{suggestion.title}</span>
                      <span className="text-xs uppercase tracking-[0.3em] text-slate-400">
                        {suggestion.category ?? "General"}
                      </span>
                    </div>
                  </button>
                ))}
            </div>
          )}
        </form>
      </div>
      <div className="flex flex-wrap gap-2">
        {categories.map((category) => {
          const slug = categorySlugFromLabel(category);
          if (!slug) return null;
          return (
            <Link
              key={category}
              href={`/categories/${encodeURIComponent(slug)}`}
              prefetch
              className="rounded-full border border-white/10 bg-slate-950/50 px-4 py-1 text-sm text-slate-200 transition hover:border-brand-400/60 hover:text-white"
            >
              {category}
            </Link>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        {quickTags.map((tag) => (
          <Link
            key={tag.slug}
            href={`/tags/${encodeURIComponent(tag.slug)}`}
            prefetch
            className="rounded-full bg-brand-500/15 px-3 py-1 text-xs font-semibold text-brand-200 transition hover:bg-brand-500/25"
          >
            #{tag.label}
          </Link>
        ))}
      </div>
    </section>
  );
}
