"use client";

import type { MarketDetail } from "@/lib/api-types";
import { useMemo } from "react";
import { formatNumber, formatTime, formatUsd, formatUsdCompact } from "@/lib/formatters";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

type Props = {
  market: MarketDetail;
};

type StatRow = {
  label: string;
  value: number | string | null | undefined;
  formatter: (v: number | string) => string;
};

const formatCount = (value?: number | null) => {
  if (value === null || value === undefined) return "—";
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
};

export function MarketAnalyticsPanel({ market }: Props) {
  const stream = usePriceStreamStore(market.eventId, market.clobTokenIds ?? []);
  const live = stream?.outcomes?.[0] ?? {};
  const lastTrade = useMemo(() => {
    const trades = stream?.trades ?? [];
    return trades.length ? trades[trades.length - 1] : null;
  }, [stream?.trades]);
  const bestBid = typeof live.bestBid === "number" && Number.isFinite(live.bestBid) ? live.bestBid : null;
  const bestAsk = typeof live.bestAsk === "number" && Number.isFinite(live.bestAsk) ? live.bestAsk : null;
  const spread =
    bestBid !== null && bestAsk !== null && bestAsk > 0 ? ((bestAsk - bestBid) / bestAsk) * 100 : null;
  const lastUpdated = stream?.lastUpdated ? formatTime(stream.lastUpdated) : null;

  const rows: Array<StatRow | null> = [
    { label: "24h volume", value: market.volume24hUsd ?? market.orderbookVolumeUsd, formatter: (v) => formatUsd(v as number) },
    { label: "Liquidity (live)", value: market.liquidityUsd, formatter: (v) => formatUsd(v as number) },
    { label: "Open interest", value: market.openInterestUsd, formatter: (v) => formatUsdCompact(v as number) },
    { label: "Best bid (Yes)", value: bestBid, formatter: (v) => `${(Number(v) * 100).toFixed(2)}%` },
    { label: "Best ask (Yes)", value: bestAsk, formatter: (v) => `${(Number(v) * 100).toFixed(2)}%` },
    { label: "Spread", value: spread, formatter: (v) => `${Number(v).toFixed(2)}%` },
    lastUpdated ? { label: "Last update", value: lastUpdated, formatter: (v) => String(v) } : null,
    lastTrade
      ? {
          label: "Last trade",
          value: lastTrade.price,
          formatter: (v) => `${Number(v).toFixed(3)} (${lastTrade.side ?? "—"})`,
        }
      : null,
    { label: "Trades (lifetime)", value: market.tradesQuantity, formatter: (v) => formatCount(v as number) },
    market.tradesQuantity !== undefined && market.tradesQuantity !== null
      ? { label: "Avg trade size", value: (market.volume24hUsd ?? 0) / Math.max(market.tradesQuantity, 1), formatter: (v) => formatUsd(v as number) }
      : null,
  ];

  const hasData = rows.some((row) => row && row.value !== undefined && row.value !== null);

  if (!hasData) return null;

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/60 p-5">
      <div className="mb-3 flex items-center justify-between text-xs uppercase tracking-[0.25em] text-slate-500">
        <span>Market stats</span>
        <span className="text-slate-400">Live streamer · subgraph fallbacks</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows
          .filter((row): row is StatRow => Boolean(row && row.value !== undefined && row.value !== null))
          .map((row) => (
            <div key={row.label} className="rounded-2xl border border-white/5 bg-slate-900/60 px-4 py-3">
              <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">{row.label}</p>
              <p className="mt-1 text-xl font-semibold text-white">
                {row.label.includes("Trades") && typeof row.value === "number"
                  ? formatNumber(row.value)
                  : row.formatter(row.value as number | string)}
              </p>
            </div>
          ))}
      </div>
    </section>
  );
}
