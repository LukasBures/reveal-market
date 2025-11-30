"use client";

import { useMemo } from "react";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { useFxStream } from "@/hooks/useFxStream";

type Props = {
  marketId: string;
  tokenIds?: string[];
};

const formatUsdCompact = (value: number | undefined): string => {
  if (value === undefined || Number.isNaN(value)) return "$—";
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value.toFixed(2)}`;
};

export function MarketFomoOverlay({ marketId, tokenIds = [] }: Props) {
  const stream = usePriceStreamStore(marketId, tokenIds);
  const { fx, status } = useFxStream("/fx/zen-usdc");
  const fxRate = fx?.zen_usd ?? 1;
  const fxFresh = status === "live" && !fx?.stale;

  const pills = useMemo(() => {
    const trades = (stream.trades || []).slice(-5).reverse();
    return trades
      .map((trade) => {
        const price = trade.price !== undefined ? Number(trade.price) : NaN;
        const size = trade.size !== undefined ? Number(trade.size) : NaN;
        // Best-effort stake approximation; Polymarket uses size * price as notional.
        const stakeZen = Number.isFinite(price) && Number.isFinite(size) ? price * size : Number.isFinite(size) ? size : Number.isFinite(price) ? price : 0;
        const stakeUsd = stakeZen * fxRate;
        return {
          label: formatUsdCompact(stakeUsd > 0 ? stakeUsd : undefined),
          side: trade.side,
          ts: trade.timestamp,
        };
      })
      .filter((pill) => pill.label !== "$—");
  }, [stream.trades, fxRate]);

  if (pills.length === 0) return null;

  return (
    <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-2 text-xs">
      {pills.slice(0, 3).map((pill, idx) => (
        <span
          key={`${pill.ts}-${idx}`}
          className={`inline-flex w-fit items-center gap-2 rounded-full px-3 py-1 font-semibold shadow-lg ${
            pill.side === "BUY" ? "bg-emerald-500/20 text-emerald-100" : "bg-sky-500/20 text-sky-100"
          }`}
        >
          {pill.label}
          <span className="text-[10px] uppercase tracking-[0.15em] text-white/70">{pill.side ?? "trade"}</span>
          {!fxFresh && <span className="text-[10px] text-amber-200">fx stale</span>}
        </span>
      ))}
    </div>
  );
}
