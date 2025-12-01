"use client";

import { useEffect, useMemo, useState } from "react";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { useFxStream } from "@/hooks/useFxStream";
import { formatTime } from "@/lib/formatters";

type Props = {
  marketId: string;
  tokenIds?: string[];
};

export function MarketLiveStatusBar({ marketId, tokenIds = [] }: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(interval);
  }, []);

  const stream = usePriceStreamStore(marketId, tokenIds);
  const fxStream = useFxStream("/fx/zen-usdc");

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

  const lastTickDate = stream.lastUpdated ? new Date(stream.lastUpdated) : null;
  const lastTick = lastTickDate ? formatTime(lastTickDate) : "—";
  const lastTickAgeSeconds = lastTickDate
    ? Math.max(0, Math.round((now - lastTickDate.getTime()) / 1000))
    : null;
  const tradeCount = stream.trades?.length ?? 0;
  const historyPoints = useMemo(
    () =>
      Object.values(stream.histories || {}).reduce(
        (acc, arr) => acc + (Array.isArray(arr) ? arr.length : 0),
        0,
      ),
    [stream.histories],
  );

  const lastTrade = stream.trades?.[stream.trades.length - 1];
  const lastTradeLabel = lastTrade?.timestamp ? formatTime(lastTrade.timestamp) : "—";

  const fxAgeSeconds = fxStream.lastUpdate > 0 ? Math.max(0, Math.round((now - fxStream.lastUpdate) / 1000)) : null;
  const fxRate = fxStream.fx?.zen_usd ? fxStream.fx.zen_usd.toFixed(4) : null;

  const fxPill = useMemo(() => {
    const className =
      fxStream.status === "error"
        ? "bg-rose-500/20 text-rose-100 border border-rose-400/30"
        : fxStream.status === "stale"
          ? "bg-amber-500/15 text-amber-100 border border-amber-400/30"
          : fxStream.status === "live"
            ? "bg-emerald-500/15 text-emerald-100 border border-emerald-400/30"
            : "bg-white/10 text-white/80 border border-white/20";
    const parts = [fxStream.wsConnected ? "WS" : "REST", fxStream.status.toUpperCase()];
    if (fxRate) parts.push(`@ ${fxRate}`);
    if (fxAgeSeconds !== null) parts.push(`${fxAgeSeconds}s`);
    return { label: parts.join(" "), className };
  }, [fxAgeSeconds, fxRate, fxStream.status, fxStream.wsConnected]);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-[12px] uppercase tracking-[0.25em] text-slate-200">
      <span className={`rounded-full px-3 py-1 text-[11px] ${connectionPill.className}`}>{connectionPill.label}</span>
      <span className={`rounded-full px-3 py-1 text-[11px] ${fxPill.className}`}>{fxPill.label}</span>
      <span
        className={`rounded-full px-3 py-1 text-[11px] ${
          fxStream.restFallbacks > 0
            ? "bg-amber-500/10 text-amber-100 border border-amber-400/30"
            : "bg-white/5 text-white/60 border border-white/10"
        }`}
      >
        FX REST {fxStream.restFallbacks}
      </span>
      <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">
        Trades {tradeCount} / Hist {historyPoints}
      </span>
      <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">Last trade {lastTradeLabel}</span>
      <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">
        Last tick {lastTick}
        {lastTickAgeSeconds !== null ? ` (${lastTickAgeSeconds}s)` : ""}
      </span>
      {stream.tickSize && (
        <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">Tick size {stream.tickSize}</span>
      )}
      {stream.error && <span className="text-rose-200">{stream.error}</span>}
    </div>
  );
}
