"use client";

import { useEffect, useState } from "react";
import { fetchFxQuote, fetchPricingQuote } from "@/lib/pricing-client";

type Props = {
  stakeZen: number;
};

export function OutcomeQuote({ stakeZen }: Props) {
  const [refundZen, setRefundZen] = useState<string>("—");
  const [profitUsd, setProfitUsd] = useState<string>("—");
  const [fxLabel, setFxLabel] = useState<string>("FX: loading…");
  const [error, setError] = useState<string | null>(null);
  const [fxStale, setFxStale] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const fx = await fetchFxQuote();
        if (cancelled) return;
        setFxLabel(`FX: 1 ZEN = ${fx.zen_usd.toFixed(4)} USD${fx.stale ? " (stale)" : ""}`);
        setFxStale(fx.stale);
        if (fx.stale) {
          setError("Pricing temporarily unavailable (stale FX)");
          return;
        }
        const quote = await fetchPricingQuote(stakeZen, fx.zen_usd);
        if (cancelled) return;
        setRefundZen(quote.refund_zen.toFixed(4));
        const profit = quote.hedge_usdc * quote.displayed_odds_multiplier - quote.hedge_usdc;
        setProfitUsd(profit.toFixed(4));
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
          setRefundZen("—");
          setProfitUsd("—");
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [stakeZen]);

  if (error) {
    return <p className="text-xs text-rose-300">Pricing unavailable: {error}</p>;
  }
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-200">
      <span className="rounded-full bg-white/10 px-2 py-1 text-white/80">{fxLabel}</span>
      <span className="rounded-full bg-emerald-500/15 px-2 py-1 text-emerald-200">
        Refund after rake: {refundZen} ZEN
      </span>
      <span className="rounded-full bg-sky-500/15 px-2 py-1 text-sky-200">
        Est. profit on {stakeZen} ZEN: {profitUsd} USDC
      </span>
      {fxStale && (
        <span className="rounded-full bg-amber-500/15 px-2 py-1 text-amber-200">
          Pricing paused due to stale FX
        </span>
      )}
    </div>
  );
}
