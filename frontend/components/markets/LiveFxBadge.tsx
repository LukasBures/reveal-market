"use client";

import { useFxStream } from "@/hooks/useFxStream";
import { formatZenUsd } from "@/lib/fx";

export function LiveFxBadge() {
  const { fx, status } = useFxStream("/fx/zen-usdc");
  const stale = status === "stale" || fx?.stale;
  const unavailable = status === "error";
  const live = status === "live" && !stale && !unavailable;
  const fxValue = formatZenUsd(fx?.zen_usd);
  const label = unavailable ? "FX unavailable" : stale ? "FX stale" : `FX live 1 ZEN = ${fxValue ?? "?"} USD`;
  const className = live
    ? "bg-emerald-500/15 text-emerald-100"
    : stale
      ? "bg-amber-500/20 text-amber-100"
      : "bg-rose-500/20 text-rose-100";
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-slate-400">
      <span className={`rounded-full px-3 py-1 ${className}`}>{label}</span>
      <span className="rounded-full bg-white/10 px-3 py-1">Live via streamer</span>
    </div>
  );
}
