"use client";

import { useEffect, useState } from "react";
import { fetchPricingQuoteWithMeta } from "@/lib/pricing-client";
import { useFxStream } from "@/hooks/useFxStream";
import { useAccount } from "wagmi";
import { formatZenUsd } from "@/lib/fx";

type Props = {
  stakeZen: number;
  marketId: string;
  marketAddress?: string | null;
  outcomeId?: number;
};

export function OutcomeQuote({ stakeZen, marketId, marketAddress, outcomeId = 0 }: Props) {
  const [refundZen, setRefundZen] = useState<string>("—");
  const [profitZen, setProfitZen] = useState<string>("—");
  const [error, setError] = useState<string | null>(null);
  const { fx, status } = useFxStream("/fx/zen-usdc");
  const fxStale = status === "stale";
  const fxValue = formatZenUsd(fx?.zen_usd);
  const fxLabel = fxValue ? `FX: 1 ZEN ≈ $${fxValue}${fxStale ? " (stale)" : ""}` : "FX: loading…";
  const { address } = useAccount();

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        if (!address || !marketAddress) {
          setError("Connect wallet to request a quote");
          return;
        }
        if (outcomeId === undefined || outcomeId === null) return;
        if (!fx || fxStale) {
          setError("Pricing temporarily unavailable (stale FX)");
          return;
        }
        // Quotes must be bound to wallet + market + outcome to match on-chain verification.
        const quote = await fetchPricingQuoteWithMeta(stakeZen, {
          marketId,
          walletAddress: address,
          outcomeId,
          marketAddress,
        });
        if (cancelled) return;
        setRefundZen(quote.refund_zen.toFixed(4));
        const profit = quote.hedge_usdc * quote.displayed_odds_multiplier - quote.hedge_usdc;
        const fxZen = Number(quote.zen_usd);
        const profitZenValue = Number.isFinite(fxZen) && fxZen > 0 ? profit / fxZen : null;
        setProfitZen(profitZenValue !== null && Number.isFinite(profitZenValue) ? profitZenValue.toFixed(4) : "—");
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
          setRefundZen("—");
          setProfitZen("—");
        }
      }
    };
    if (fx) load();
    return () => {
      cancelled = true;
    };
  }, [stakeZen, marketId, fx, fxStale, address, marketAddress, outcomeId]);

  useEffect(() => {
    // Auto-refresh on quote expiry
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = async () => {
      try {
        if (!fx || fxStale || !stakeZen || !address || !marketAddress) return;
        const quote = await fetchPricingQuoteWithMeta(stakeZen, {
          marketId,
          walletAddress: address,
          outcomeId,
          marketAddress,
        });
        const expires = new Date(quote.expires_at).getTime();
        const delay = Math.max(expires - Date.now() - 1_000, 0);
        timer = setTimeout(schedule, delay);
      } catch {
        /* ignore */
      }
    };
    schedule();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [fx, fxStale, stakeZen, marketId, address, marketAddress, outcomeId]);

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
        Est. profit on {stakeZen} ZEN: {profitZen} ZEN
      </span>
      {fxStale && (
        <span className="rounded-full bg-amber-500/15 px-2 py-1 text-amber-200">
          Pricing paused due to stale FX
        </span>
      )}
    </div>
  );
}
