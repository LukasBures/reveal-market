"use client";

import { useMemo } from "react";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

type Props = {
  marketId: string;
};

export function MarketLivePanels({ marketId }: Props) {
  const stream = usePriceStreamStore(marketId);
  const best = stream.outcomes[0] || {};
  const trades = useMemo(
    () =>
      (stream.trades || [])
        .slice(-10)
        .reverse()
        .map((t) => ({
          ...t,
          label: t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : "",
        })),
    [stream.trades],
  );

  return (
    <div className="flex h-full flex-col gap-4 rounded-3xl border border-white/10 bg-slate-900/50 p-4">
      <div className="flex items-center justify-between text-sm text-slate-200">
        <span className="text-xs uppercase tracking-[0.25em] text-slate-500">
          Live order flow {stream.connected ? "" : "(reconnecting…)"}
        </span>
        {stream.tickSize && (
          <span className="rounded-full bg-white/10 px-2 py-1 text-[11px] uppercase tracking-[0.2em] text-white/70">
            Tick size {stream.tickSize}
          </span>
        )}
      </div>
      <div className="rounded-2xl border border-white/5 bg-slate-950/70 p-3 text-sm text-slate-200">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Best bid</span>
          <span>Best ask</span>
        </div>
        <div className="mt-2 flex items-center justify-between text-lg font-semibold">
          <span className="text-emerald-300">{best.bestBid ? best.bestBid.toFixed(3) : "—"}</span>
          <span className="text-sky-300">{best.bestAsk ? best.bestAsk.toFixed(3) : "—"}</span>
        </div>
        {best.bestBid && best.bestAsk && (
          <p className="mt-1 text-xs text-slate-400">
            Spread {best.bestAsk > 0 ? (((best.bestAsk - best.bestBid) / best.bestAsk) * 100).toFixed(2) : "—"}%
          </p>
        )}
      </div>
      <div className="flex-1 rounded-2xl border border-white/5 bg-slate-950/70 p-3">
        <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-slate-500">
          <span>Recent trades</span>
          <span className="text-slate-400">{trades.length ? "" : "Waiting…"}</span>
        </div>
        <div className="mt-2 flex flex-col gap-1">
          {trades.map((trade, idx) => (
            <div
              key={`${trade.timestamp}-${idx}`}
              className="flex items-center justify-between rounded-xl bg-white/5 px-2 py-1 text-xs text-slate-200"
            >
              <span className={trade.side === "BUY" ? "text-emerald-300" : "text-rose-300"}>
                {trade.side ?? "—"}
              </span>
              <span>{trade.price !== undefined ? Number(trade.price).toFixed(3) : "—"}</span>
              <span className="text-slate-400">{trade.size ? Number(trade.size).toFixed(2) : "—"}</span>
              <span className="text-slate-500">{trade.label}</span>
            </div>
          ))}
          {trades.length === 0 && (
            <div className="rounded-xl border border-dashed border-white/10 bg-white/5 px-3 py-4 text-center text-slate-400">
              No trades yet—stay tuned for the next print.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
