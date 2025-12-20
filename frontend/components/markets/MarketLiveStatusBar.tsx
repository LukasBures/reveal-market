"use client";

import { useEffect, useMemo, useState } from "react";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { useFxStream } from "@/hooks/useFxStream";
import { FX_DEFAULT_PATH } from "@/lib/pricing-client";
import { formatTime } from "@/lib/formatters";

type Props = {
  marketId: string;
  tokenIds?: string[];
};

function useVisibleNow() {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (typeof document === "undefined") return;
    let interval: ReturnType<typeof setInterval> | null = null;
    const tick = () => setNow(Date.now());
    const start = () => {
      if (interval) return;
      interval = setInterval(tick, 1_000);
    };
    const stop = () => {
      if (!interval) return;
      clearInterval(interval);
      interval = null;
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        tick();
        start();
      } else {
        stop();
      }
    };
    handleVisibility();
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);
  return now;
}

function FxStatusPill({ fxStream }: { fxStream: ReturnType<typeof useFxStream> }) {
  const now = useVisibleNow();
  const fxAgeSeconds =
    now !== null && fxStream.lastUpdate > 0 ? Math.max(0, Math.round((now - fxStream.lastUpdate) / 1000)) : null;
  const fxRate = fxStream.fx?.zen_usd ? fxStream.fx.zen_usd.toFixed(4) : null;
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
  return <span className={`rounded-full px-3 py-1 text-[11px] ${className}`}>{parts.join(" ")}</span>;
}

function LastTickPill({ lastUpdated }: { lastUpdated?: string | null }) {
  const now = useVisibleNow();
  const lastTickDate = lastUpdated ? new Date(lastUpdated) : null;
  const lastTick = lastTickDate ? formatTime(lastTickDate) : "—";
  const lastTickAgeSeconds = now !== null && lastTickDate
    ? Math.max(0, Math.round((now - lastTickDate.getTime()) / 1000))
    : null;
  return (
    <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">
      Last tick {lastTick}
      {lastTickAgeSeconds !== null ? ` (${lastTickAgeSeconds}s)` : ""}
    </span>
  );
}

export function MarketLiveStatusBar({ marketId, tokenIds = [] }: Props) {
  const stream = usePriceStreamStore(marketId, tokenIds);
  const fxStream = useFxStream(FX_DEFAULT_PATH);

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

  const tradeCount = stream.trades?.length ?? 0;
  const historyPoints = Number.isFinite(stream.historyCount)
    ? stream.historyCount
    : Object.values(stream.histories || {}).reduce(
        (acc, arr) => acc + (Array.isArray(arr) ? arr.length : 0),
        0,
      );

  const lastTrade = stream.trades?.[stream.trades.length - 1];
  const lastTradeLabel = lastTrade?.timestamp ? formatTime(lastTrade.timestamp) : "—";

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-[12px] uppercase tracking-[0.25em] text-slate-200">
      <span className={`rounded-full px-3 py-1 text-[11px] ${connectionPill.className}`}>{connectionPill.label}</span>
      <FxStatusPill fxStream={fxStream} />
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
      <LastTickPill lastUpdated={stream.lastUpdated} />
      {stream.tickSize && (
        <span className="rounded-full bg-white/5 px-3 py-1 text-[11px] text-white/70">Tick size {stream.tickSize}</span>
      )}
      {stream.error && <span className="text-rose-200">{stream.error}</span>}
    </div>
  );
}
