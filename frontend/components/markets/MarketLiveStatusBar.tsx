"use client";

import { useMemo } from "react";
import { useFxStream } from "@/hooks/useFxStream";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";

type Props = {
  marketId: string;
  tokenIds?: string[];
};

export function MarketLiveStatusBar({ marketId, tokenIds = [] }: Props) {
  const stream = usePriceStreamStore(marketId, tokenIds);
  const { fx, status: fxStatus } = useFxStream("/fx/zen-usdc");

  const connectionPill = useMemo(() => {
    if (stream.error) {
      return { label: "Stream error", className: "bg-rose-500/20 text-rose-100 border border-rose-400/30" };
    }
    if (stream.connected) {
      const transport = stream.transport ? stream.transport.toUpperCase() : "LIVE";
      return { label: `Live (${transport})`, className: "bg-emerald-500/15 text-emerald-100 border border-emerald-400/30" };
    }
    return { label: "Reconnecting…", className: "bg-amber-500/15 text-amber-100 border border-amber-400/30" };
  }, [stream.connected, stream.error, stream.transport]);

  const fxPill = useMemo(() => {
    if (fxStatus === "error") {
      return { label: "FX unavailable", className: "bg-rose-500/20 text-rose-100 border border-rose-400/30" };
    }
    if (fxStatus === "stale" || fx?.stale) {
      return { label: "FX stale", className: "bg-amber-500/20 text-amber-100 border border-amber-400/30" };
    }
    return { label: "FX live", className: "bg-emerald-500/15 text-emerald-100 border border-emerald-400/30" };
  }, [fx?.stale, fxStatus]);

  const lastTick = stream.lastUpdated ? new Date(stream.lastUpdated).toLocaleTimeString() : "—";

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-[12px] uppercase tracking-[0.25em] text-slate-200">
      <span className={`rounded-full px-3 py-1 text-[11px] ${connectionPill.className}`}>{connectionPill.label}</span>
      <span className={`rounded-full px-3 py-1 text-[11px] ${fxPill.className}`}>{fxPill.label}</span>
      <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">
        Last tick {lastTick}
      </span>
      {stream.tickSize && (
        <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">Tick size {stream.tickSize}</span>
      )}
      {stream.error && <span className="text-rose-200">{stream.error}</span>}
    </div>
  );
}
