"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchFxQuote, fetchPricingQuote, type FxQuote, type PricingQuote } from "@/lib/pricing-client";

type Props = {
  defaultStakeZen?: number;
};

const formatNumber = (value: number, decimals = 4) => {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(decimals);
};

export function StakeQuoteCard({ defaultStakeZen = 10 }: Props) {
  const [stakeZen, setStakeZen] = useState<number>(defaultStakeZen);
  const [fx, setFx] = useState<FxQuote | null>(null);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadFx = async () => {
      try {
        const payload = await fetchFxQuote();
        if (!cancelled) setFx(payload);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    };
    loadFx();
    return () => {
      cancelled = true;
    };
  }, []);

  const debouncedStake = useDebounce(stakeZen, 200);

  useEffect(() => {
    if (!fx || !Number.isFinite(debouncedStake) || debouncedStake <= 0) {
      setQuote(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchPricingQuote(debouncedStake, fx.zen_usd)
      .then((payload) => {
        if (!cancelled) {
          setQuote(payload);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedStake, fx]);

  const profitUsd = useMemo(() => {
    if (!quote) return null;
    return quote.hedge_usdc * quote.displayed_odds_multiplier - quote.hedge_usdc;
  }, [quote]);

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/60 p-5 text-sm text-slate-100 shadow-lg shadow-black/20">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Preview payout</p>
          <p className="text-lg font-semibold text-white">Live quote (ZEN in / USDC profit)</p>
        </div>
        {fx && (
          <span className="rounded-full bg-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.3em] text-white/80">
            FX: 1 ZEN = {formatNumber(fx.zen_usd, 4)} USD{fx.stale ? " (stale)" : ""}
          </span>
        )}
      </div>
      <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Stake (ZEN)</span>
          <input
            type="number"
            min={0}
            step="0.01"
            value={stakeZen}
            onChange={(e) => setStakeZen(Number(e.target.value))}
            className="w-full rounded-xl border border-white/15 bg-slate-900/70 px-3 py-2 text-white outline-none transition focus:border-emerald-400"
          />
        </label>
        <div className="grid flex-1 grid-cols-2 gap-3 text-xs md:grid-cols-3">
          <Metric label="Refund (ZEN)" value={formatNumber(quote?.refund_zen ?? NaN, 4)} />
          <Metric label="Rake (ZEN)" value={formatNumber(quote?.rake_zen ?? NaN, 4)} />
          <Metric label="Hedge size (USDC)" value={formatNumber(quote?.hedge_usdc ?? NaN, 4)} />
          <Metric label="Displayed odds" value={formatNumber(quote?.displayed_odds_multiplier ?? NaN, 3)} />
          <Metric label="Est. profit (USDC)" value={formatNumber(profitUsd ?? NaN, 4)} highlight />
          <Metric label="Total monetisation" value={formatNumber(quote?.total_monetisation ?? NaN, 3)} />
        </div>
      </div>
      {loading && <p className="mt-2 text-xs text-slate-400">Fetching quote…</p>}
      {error && (
        <p className="mt-2 text-xs text-rose-300">
          {error}. FX feed or pricing may be temporarily unavailable.
        </p>
      )}
    </div>
  );
}

function Metric({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2">
      <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">{label}</p>
      <p className={`text-sm font-semibold ${highlight ? "text-emerald-200" : "text-white"}`}>{value}</p>
    </div>
  );
}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}
