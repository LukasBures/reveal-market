"use client";

import { useMemo } from "react";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { formatTime } from "@/lib/formatters";

type Props = {
  marketId: string;
  tokenIds?: string[];
};

export function MarketLivePanels({ marketId, tokenIds = [] }: Props) {
  const stream = usePriceStreamStore(marketId, tokenIds);
  const best = stream.outcomes[0] || {};
  const depthBids = best.depthBids || [];
  const depthAsks = best.depthAsks || [];
  const statusText = stream.error
    ? "Stream error"
    : stream.connected
      ? stream.transport === "ws"
        ? "Live (WS)"
        : "Live (SSE)"
      : "Reconnecting...";
  const statusClass = stream.error
    ? "bg-rose-500/20 text-rose-200 border border-rose-500/30"
    : stream.connected
      ? "bg-emerald-500/15 text-emerald-100 border border-emerald-500/30"
      : "bg-amber-500/15 text-amber-100 border border-amber-500/30";
  const transportText = stream.transport ? stream.transport.toUpperCase() : "N/A";
  const transportClass = stream.connected
    ? "bg-white/10 text-white/80 border border-white/20"
    : "bg-amber-500/15 text-amber-100 border border-amber-400/30";
  const fxClass = stream.fxStale
    ? "bg-amber-500/20 text-amber-100 border border-amber-400/40"
    : "bg-emerald-500/15 text-emerald-100 border border-emerald-400/30";
  const spread =
    best.bestBid !== undefined && best.bestAsk !== undefined && best.bestAsk > 0
      ? ((best.bestAsk - best.bestBid) / best.bestAsk) * 100
      : null;
  const trades = useMemo(
    () =>
      (stream.trades || [])
        .slice(-10)
        .reverse()
        .map((t) => ({
          ...t,
          label: t.timestamp ? formatTime(t.timestamp) : "",
        })),
    [stream.trades],
  );

  return (
    <div className="flex flex-col gap-4 rounded-3xl border border-white/10 bg-slate-900/50 p-4">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-[12px] uppercase tracking-[0.25em] text-slate-200">
        <span className={`rounded-full px-3 py-1 text-[11px] ${statusClass}`}>{statusText}</span>
        <span className={`rounded-full px-3 py-1 text-[11px] ${transportClass}`}>Transport {transportText}</span>
        <span className={`rounded-full px-3 py-1 text-[11px] ${fxClass}`}>
          FX {stream.fxStale ? "stale" : "live"}
        </span>
        <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">
          Last tick {stream.lastUpdated ? formatTime(stream.lastUpdated) : "—"}
        </span>
        {stream.tickSize && (
          <span className="rounded-full bg-white/10 px-3 py-1 text-[11px] text-white/70">Tick size {stream.tickSize}</span>
        )}
        {stream.error && (
          <span className="rounded-full bg-rose-500/15 px-3 py-1 text-[11px] text-rose-100 border border-rose-400/40">
            Stream error
          </span>
        )}
      </div>
      {stream.error && (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-100">
          {stream.error}
        </div>
      )}
      <div className="rounded-2xl border border-white/5 bg-slate-950/70 p-3 text-sm text-slate-200">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <span>Best bid</span>
          <span>Best ask</span>
          <span className="text-slate-500">Spread</span>
        </div>
        <div className="mt-2 grid grid-cols-3 items-center text-lg font-semibold">
          <span className="text-emerald-300">{best.bestBid ? best.bestBid.toFixed(3) : "—"}</span>
          <span className="text-sky-300">{best.bestAsk ? best.bestAsk.toFixed(3) : "—"}</span>
          <span className="text-slate-100">{spread !== null ? `${spread.toFixed(2)}%` : "—"}</span>
        </div>
        {stream.lastUpdated && (
          <p className="mt-1 text-xs text-slate-500">Updated {formatTime(stream.lastUpdated)}</p>
        )}
      </div>
      <div className="rounded-2xl border border-white/5 bg-slate-950/70 p-3">
        <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-slate-500">
          <span>Order book depth</span>
          <span className="text-slate-400">Top 5</span>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-200">
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-2">
            <div className="flex justify-between text-[11px] uppercase tracking-[0.15em] text-emerald-200">
              <span>Bids</span>
              <span>Size</span>
            </div>
            <div className="mt-1 space-y-1">
              {(depthBids.length ? depthBids : [{ price: undefined, size: undefined }]).map((row, idx) => (
                <div key={`bid-${idx}`} className="flex justify-between">
                  <span className="text-emerald-200">{row.price !== undefined ? row.price.toFixed(3) : "—"}</span>
                  <span className="text-emerald-100">{row.size !== undefined ? row.size.toFixed(2) : "—"}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="rounded-xl border border-sky-500/20 bg-sky-500/5 p-2">
            <div className="flex justify-between text-[11px] uppercase tracking-[0.15em] text-sky-200">
              <span>Asks</span>
              <span>Size</span>
            </div>
            <div className="mt-1 space-y-1">
              {(depthAsks.length ? depthAsks : [{ price: undefined, size: undefined }]).map((row, idx) => (
                <div key={`ask-${idx}`} className="flex justify-between">
                  <span className="text-sky-200">{row.price !== undefined ? row.price.toFixed(3) : "—"}</span>
                  <span className="text-sky-100">{row.size !== undefined ? row.size.toFixed(2) : "—"}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="rounded-2xl border border-white/5 bg-slate-950/70 p-3">
        <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-slate-500">
          <span>Recent trades</span>
          <span className="text-slate-400">{trades.length ? "" : "Waiting..."}</span>
        </div>
        <div className="mt-2 flex max-h-52 flex-col gap-1 overflow-y-auto">
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
              <span className="text-slate-500">
                {trade.label ? formatTime(trade.timestamp, { hour: "2-digit", minute: "2-digit" }) : "—"}
              </span>
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
