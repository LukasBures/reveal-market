import type { MarketDetail } from "@/lib/api-types";
import { formatUsd } from "@/lib/formatters";

type Props = {
  market: MarketDetail;
};

const formatCount = (value?: number | null) => {
  if (value === null || value === undefined) return "—";
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
};

export function MarketAnalyticsPanel({ market }: Props) {
  const rows = [
    { label: "Orderbook volume", value: market.orderbookVolumeUsd ?? market.volume24hUsd, formatter: formatUsd },
    { label: "Open interest", value: market.openInterestUsd, formatter: formatUsd },
    { label: "Trades", value: market.tradesQuantity, formatter: formatCount },
  ];

  const hasData = rows.some((row) => row.value !== undefined && row.value !== null);

  if (!hasData) return null;

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/60 p-5">
      <div className="mb-3 flex items-center justify-between text-xs uppercase tracking-[0.25em] text-slate-500">
        <span>Market stats</span>
        <span className="text-slate-400">Streamer · Subgraph</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {rows.map((row) => (
          <div key={row.label} className="rounded-2xl border border-white/5 bg-slate-900/60 px-4 py-3">
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">{row.label}</p>
            <p className="mt-1 text-xl font-semibold text-white">{row.formatter(row.value as any)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
