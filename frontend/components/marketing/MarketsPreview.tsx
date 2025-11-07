"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { fetchFeaturedMarkets, type MarketSummary } from "@/lib/api";

type Props = {
  initialMarkets: MarketSummary[];
};

export function MarketsPreviewClient({ initialMarkets }: Props) {
  const { data, refetch, isFetching } = useQuery({
    queryKey: ["markets", "preview"],
    queryFn: () => fetchFeaturedMarkets(6),
    initialData: initialMarkets,
    refetchInterval: 30_000,
  });

  useEffect(() => {
    // Prefetch as soon as component mounts to keep SSR/cache fresh.
    void refetch();
  }, [refetch]);

  const markets = data ?? [];

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {markets.map((market) => (
        <article
          key={market.eventId}
          className="rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/70 to-slate-900/30 p-5 shadow-lg ring-1 ring-black/5"
        >
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
            {market.category}
          </p>
          <h3 className="mt-2 text-xl font-semibold text-white">
            {market.title}
          </h3>
          <div className="mt-4 flex flex-wrap gap-3 text-sm text-slate-400">
            <span>
              Commit ends:{" "}
              <strong className="text-white">
                {market.commitDeadline
                  ? new Date(market.commitDeadline).toLocaleString()
                  : "TBA"}
              </strong>
            </span>
            <span>
              Reveal ends:{" "}
              <strong className="text-white">
                {market.revealDeadline
                  ? new Date(market.revealDeadline).toLocaleString()
                  : "TBA"}
              </strong>
            </span>
          </div>
          <div className="mt-4 flex items-center justify-between text-sm">
            <span className="rounded-full bg-white/10 px-3 py-1 text-slate-200">
              {market.status ?? "unknown"}
            </span>
            <span className="text-slate-300">
              Liquidity: $
              {market.liquidityUsd
                ? market.liquidityUsd.toLocaleString(undefined, {
                    maximumFractionDigits: 0,
                  })
                : "—"}
            </span>
          </div>
        </article>
      ))}
      {!markets.length && !isFetching && (
        <p className="text-center text-slate-400">
          Markets will appear here once the API is seeded.
        </p>
      )}
    </div>
  );
}
