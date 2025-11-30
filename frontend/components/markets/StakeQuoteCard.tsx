"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchPricingQuoteWithMeta, type PricingQuote } from "@/lib/pricing-client";
import { useFxStream } from "@/hooks/useFxStream";
import { useAccount } from "wagmi";

type Props = {
  defaultStakeZen?: number;
  marketAddress?: string | null;
  marketId?: string;
  outcomes?: string[];
  initialOutcomeId?: number;
  outcomePrices?: number[];
};

const DEFAULT_MAX_STAKE_ZEN = 100;

const formatNumber = (value: number, decimals = 4) => {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(decimals);
};

export function StakeQuoteCard({
  defaultStakeZen = 10,
  marketAddress,
  marketId,
  outcomes = [],
  initialOutcomeId = 0,
  outcomePrices = [],
}: Props) {
  const [stakeZen, setStakeZen] = useState<number>(defaultStakeZen);
  const [selectedOutcome, setSelectedOutcome] = useState<number>(initialOutcomeId);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const { fx, status } = useFxStream("/fx/zen-usdc");
  const fxStale = status === "stale";
  const fxLive = status === "live" && !fx?.stale;
  const { address } = useAccount();
  const fxUnavailable = status === "error";
  const outcomeOptions = useMemo(() => (outcomes.length ? outcomes : ["Yes", "No"]), [outcomes]);
  const isBinary = outcomeOptions.length === 2;
  const normalizedPrices = Array.isArray(outcomePrices) ? outcomePrices : [];
  const priceForOutcome = (index: number): number | null => {
    const value = normalizedPrices[index];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    return null;
  };
  const outcomeLabel =
    outcomeOptions[selectedOutcome] ??
    (selectedOutcome === 0 ? "Yes" : selectedOutcome === 1 ? "No" : `Outcome ${selectedOutcome + 1}`);

  const debouncedStake = useDebounce(stakeZen, 200);
  const effectiveMaxStake = useMemo(() => {
    const caps = [
      DEFAULT_MAX_STAKE_ZEN,
      quote?.max_stake_zen ?? null,
      quote?.remaining_user_stake_zen ?? null,
      quote?.remaining_market_stake_zen ?? null,
      quote?.max_user_stake_per_market_zen ?? null,
      quote?.max_market_stake_zen ?? null,
    ]
      .filter((v): v is number => v !== null && v !== undefined && !Number.isNaN(v))
      .map((v) => Math.max(0, v));
    if (!caps.length) return DEFAULT_MAX_STAKE_ZEN;
    return Math.max(0.01, Math.min(...caps));
  }, [quote]);

  useEffect(() => {
    if (selectedOutcome >= outcomeOptions.length) {
      setSelectedOutcome(0);
    }
  }, [outcomeOptions, selectedOutcome]);

  useEffect(() => {
    let cancelled = false;
    const requestQuote = async () => {
      if (!address) {
        setQuote(null);
        setError("Connect wallet to request a quote");
        return;
      }
      if (!marketAddress) {
        setQuote(null);
        setError("Missing market address for quote");
        return;
      }
      if (fxUnavailable) {
        setQuote(null);
        setError("FX feed unavailable");
        return;
      }
      if (!fx || fx.stale || !Number.isFinite(debouncedStake) || debouncedStake <= 0) {
        setQuote(null);
        if (fx?.stale) setError("Pricing paused (FX stale)");
        return;
      }
      const cappedStake = Math.min(debouncedStake, effectiveMaxStake);
      if (cappedStake !== debouncedStake) {
        setStakeZen(cappedStake);
        setError(`Adjusted stake to cap (${cappedStake.toFixed(3)} ZEN)`);
      }
      setLoading(true);
      try {
        const payload = await fetchPricingQuoteWithMeta(cappedStake, {
          marketId,
          walletAddress: address,
          marketAddress,
          outcomeId: selectedOutcome,
        });
        if (!cancelled) {
          setQuote(payload);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    requestQuote();
    return () => {
      cancelled = true;
    };
  }, [debouncedStake, fx, address, marketAddress, marketId, selectedOutcome, fxUnavailable, refreshNonce, effectiveMaxStake]);

  useEffect(() => {
    if (!quote) return;
    const expires = new Date(quote.expires_at).getTime();
    const delay = expires - Date.now() - 1_000;
    const timer = setTimeout(() => {
      setQuote(null); // trigger refetch via effect above
    }, Math.max(delay, 0));
    return () => clearTimeout(timer);
  }, [quote]);

  const profitUsd = useMemo(() => {
    if (!quote) return null;
    return quote.hedge_usdc * quote.displayed_odds_multiplier - quote.hedge_usdc;
  }, [quote]);
  const currentPrice = priceForOutcome(selectedOutcome);
  const ctaLabel = loading
    ? "Pricing…"
    : `Buy ${outcomeLabel}${currentPrice !== null ? ` @ $${currentPrice.toFixed(3)}` : ""}`;

  return (
    <div className="md:sticky md:top-28 rounded-3xl border border-white/10 bg-slate-950/80 p-5 text-sm text-slate-100 shadow-xl shadow-black/30 backdrop-blur">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Trade</p>
          <p className="text-lg font-semibold text-white">Buy/Sell {outcomeLabel}</p>
          <p className="text-xs text-slate-400">
            Live quotes with FX applied. Max stake {effectiveMaxStake.toFixed(3)} ZEN (API caps).
          </p>
        </div>
        <div className="flex flex-col items-end gap-2 text-[11px] uppercase tracking-[0.2em]">
          <span
            className={`rounded-full px-3 py-1 ${
              fxLive ? "bg-emerald-500/15 text-emerald-100" : fxStale || fxUnavailable ? "bg-amber-500/20 text-amber-100" : "bg-white/10 text-white/70"
            }`}
          >
            FX {fxLive ? "live" : fxUnavailable ? "unavailable" : "stale"}
          </span>
          {quote && (
            <span className="rounded-full bg-white/10 px-3 py-1 text-white/80">
              Quote {quote.quote_id.slice(0, 6)}… expires {new Date(quote.expires_at).toLocaleTimeString()}
            </span>
          )}
          {quote && (
            <span className="rounded-full bg-white/5 px-3 py-1 text-[10px] text-white/70">
              Caps — user {quote.remaining_user_stake_zen?.toFixed(2) ?? "n/a"} ZEN · market{" "}
              {quote.remaining_market_stake_zen?.toFixed(2) ?? "n/a"} ZEN
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {isBinary ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[0, 1].map((idx) => {
              const label = outcomeOptions[idx] ?? (idx === 0 ? "Yes" : "No");
              const price = priceForOutcome(idx);
              const formattedPrice = price !== null ? `$${price.toFixed(3)}` : "—";
              const active = selectedOutcome === idx;
              return (
                <button
                  key={`${label}-${idx}`}
                  type="button"
                  onClick={() => setSelectedOutcome(idx)}
                  className={`flex flex-col gap-1 rounded-2xl border px-4 py-3 text-left transition ${
                    active
                      ? "border-emerald-400 bg-emerald-500/15 text-white"
                      : "border-white/10 bg-white/5 text-white/80 hover:border-white/30 hover:bg-white/10"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold uppercase tracking-[0.25em]">Buy {label}</span>
                    <span className="text-sm font-semibold text-emerald-200">{formattedPrice}</span>
                  </div>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400">
                    {idx === 0 ? "Back the yes side" : "Back the no side"}
                  </p>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {outcomeOptions.map((label, idx) => (
              <button
                key={`${label}-${idx}`}
                type="button"
                onClick={() => setSelectedOutcome(idx)}
                className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] transition ${
                  selectedOutcome === idx ? "bg-white text-slate-900" : "bg-white/10 text-white/80 hover:bg-white/20"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 space-y-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Stake (ZEN)</span>
          <input
            type="number"
            min={0}
            max={effectiveMaxStake}
            step="0.01"
            value={stakeZen}
            onChange={(e) => {
              const next = Number(e.target.value);
              if (Number.isNaN(next)) {
                setStakeZen(0);
                return;
              }
              const capped = Math.min(Math.max(next, 0), effectiveMaxStake);
              setStakeZen(capped);
            }}
            className="w-full rounded-xl border border-white/15 bg-slate-900/80 px-3 py-2 text-white outline-none transition focus:border-emerald-400"
          />
          <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
            {[5, 10, 25, 50].map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setStakeZen(Math.min(preset, effectiveMaxStake))}
                className="rounded-full bg-white/5 px-3 py-1 font-semibold uppercase tracking-[0.2em] text-white/80 hover:bg-white/15"
              >
                {preset} ZEN
              </button>
            ))}
          </div>
        </label>
        <div className="grid grid-cols-2 gap-3 text-xs">
          <Metric label="Refund (ZEN)" value={formatNumber(quote?.refund_zen ?? NaN, 3)} />
          <Metric label="Rake (ZEN)" value={formatNumber(quote?.rake_zen ?? NaN, 3)} />
          <Metric label="Profit (USDC)" value={formatNumber(profitUsd ?? NaN, 3)} highlight />
          <Metric label="Odds" value={formatNumber(quote?.displayed_odds_multiplier ?? NaN, 3)} />
          <Metric label="Quote expiry" value={quote ? new Date(quote.expires_at).toLocaleTimeString() : "—"} />
          <Metric
            label="Chain"
            value={
              quote?.chain_id !== undefined && quote?.chain_id !== null
                ? String(quote.chain_id)
                : "—"
            }
          />
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-2">
        <button
          type="button"
          disabled={loading || fxStale || fxUnavailable || !address || !marketAddress}
          onClick={() => setRefreshNonce((prev) => prev + 1)}
          className={`inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] transition ${
            loading || fxStale || fxUnavailable || !address || !marketAddress
              ? "cursor-not-allowed bg-white/20 text-white/60"
              : "bg-emerald-500 text-white hover:bg-emerald-400"
          }`}
        >
          {ctaLabel}
        </button>
        {quote && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
            Caps — user:{" "}
            {quote.remaining_user_stake_zen !== null && quote.remaining_user_stake_zen !== undefined
              ? `${formatNumber(quote.remaining_user_stake_zen, 3)} ZEN`
              : "n/a"}
            , market:{" "}
            {quote.remaining_market_stake_zen !== null && quote.remaining_market_stake_zen !== undefined
              ? `${formatNumber(quote.remaining_market_stake_zen, 3)} ZEN`
              : "n/a"}
          </p>
        )}
        {error && <p className="text-xs text-rose-300">{error}</p>}
        {fxStale && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-300">
            Pricing paused due to stale FX. Please retry in a moment.
          </p>
        )}
      </div>
      {quote && (
        <div className="mt-4 rounded-2xl border border-white/10 bg-slate-900/60 p-3 text-xs text-slate-300">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Trade summary</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <span>Stake: {formatNumber(quote.stake_zen, 3)} ZEN</span>
            <span>Refund: {formatNumber(quote.refund_zen, 3)} ZEN</span>
            <span>Profit: {formatNumber(profitUsd ?? NaN, 3)} USDC</span>
            <span>Haircut: {formatNumber(quote.haircut_percent * 100, 2)}%</span>
            <span>Worsen: {formatNumber(quote.worsen_percent * 100, 2)}%</span>
            <span>Rake: {formatNumber(quote.rake_percent * 100, 2)}%</span>
          </div>
        </div>
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
