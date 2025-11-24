 "use client";

import Link from "next/link";
import type { MarketDetail } from "@/lib/api-types";
import { useEffect, useMemo, useState } from "react";
import { fetchFxQuote, fetchPricingQuoteWithMeta, type FxQuote, type PricingQuote } from "@/lib/pricing-client";
import { OutcomeQuote } from "./OutcomeQuote";

type Props = {
  market: MarketDetail;
};

const MAX_STAKE_ZEN = 100;

const formatZen = (value: number | undefined): string => {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(3)} ZEN`;
};

export function MarketDetailOutcomes({ market }: Props) {
  const outcomes = market.outcomes ?? [];
  const prices = market.outcomePrices ?? [];
  const [selectedOutcome, setSelectedOutcome] = useState(0);
  const [stakeZen, setStakeZen] = useState(10);
  const [fx, setFx] = useState<FxQuote | null>(null);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const loadFx = async () => {
      try {
        const payload = await fetchFxQuote();
        if (cancelled) return;
        setFx(payload);
        if (payload.stale) {
          setError("Pricing paused (FX stale)");
        } else {
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    };
    loadFx();
    const id = setInterval(loadFx, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!fx || fx.stale || stakeZen <= 0) {
      setQuote(null);
      return;
    }
    if (stakeZen > MAX_STAKE_ZEN) {
      setQuote(null);
      setError(`Max stake per bet is ${MAX_STAKE_ZEN} ZEN`);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchPricingQuoteWithMeta(stakeZen, fx.zen_usd, { marketId: market.eventId })
      .then((payload) => {
        if (cancelled) return;
        setQuote(payload);
        setError(null);
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
  }, [fx, stakeZen, market.eventId]);

  const profitUsd = useMemo(() => {
    if (!quote) return null;
    return quote.hedge_usdc * quote.displayed_odds_multiplier - quote.hedge_usdc;
  }, [quote]);

  if (outcomes.length === 0) {
    return (
      <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-slate-400">
        No outcome data available.
      </div>
    );
  }

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/40 p-4 sm:p-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Tradable outcomes</p>
          <h2 className="text-xl font-semibold text-white leading-snug">{market.title}</h2>
          <p className="text-sm text-slate-400">Pick your side below and trade directly from this page.</p>
        </div>
        <span className="rounded-full bg-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.3em] text-white/70">
          Prices shown in ZEN
        </span>
      </div>
      <OutcomeQuote stakeZen={10} marketId={market.eventId} />
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm text-slate-200">
          <thead>
            <tr className="text-left text-xs uppercase tracking-[0.25em] text-slate-500">
              <th className="py-2">Outcome</th>
              <th className="py-2">Odds</th>
              <th className="py-2">Est. price</th>
              <th className="py-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {outcomes.map((outcome, idx) => {
              const price = typeof prices[idx] === "number" ? prices[idx] : undefined;
              const probability = price !== undefined ? `${Math.round(price * 100)}%` : "—";
              const href = `/markets/${market.eventId}?outcome=${encodeURIComponent(String(idx))}`;
              const isYes = idx === 0;
              const isNo = idx === 1;
              return (
                <tr key={outcome} className="border-t border-white/5">
                  <td className="py-3 font-semibold text-white">{outcome}</td>
                  <td className="py-3 text-slate-300">{probability}</td>
                  <td className="py-3 text-slate-300">{formatZen(price)}</td>
                  <td className="py-3 text-right">
                    <Link
                      href={{ pathname: "/markets/[eventId]", query: { eventId: market.eventId, outcome: String(idx) } }}
                      className={`inline-flex w-full sm:w-[180px] items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] text-white transition ${
                        isYes
                          ? "bg-emerald-500 hover:bg-emerald-400"
                          : isNo
                            ? "bg-rose-500 hover:bg-rose-400"
                            : "bg-white/20 hover:bg-white/30"
                      }`}
                    >
                      {isYes ? "Buy YES" : isNo ? "Buy NO" : `Buy ${outcome}`}
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-4 rounded-3xl border border-white/10 bg-slate-950/60 p-4 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Place a trade</p>
            <p className="text-sm text-slate-200">Enter stake in ZEN to preview rake, refund, and USDC profit.</p>
          </div>
          <div className="flex items-center gap-2">
            {outcomes.map((outcome, idx) => (
              <button
                key={outcome}
                type="button"
                onClick={() => setSelectedOutcome(idx)}
                className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] transition ${
                  selectedOutcome === idx ? "bg-white text-slate-900" : "bg-white/10 text-white/80 hover:bg-white/20"
                }`}
              >
                {outcome}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="flex flex-1 flex-col gap-1 text-xs uppercase tracking-[0.2em] text-slate-500">
            Stake (ZEN)
            <input
              type="number"
              min={0}
              max={MAX_STAKE_ZEN}
              step="0.01"
              value={stakeZen}
              onChange={(e) => {
                const next = Number(e.target.value);
                if (Number.isNaN(next)) {
                  setStakeZen(0);
                  return;
                }
                setStakeZen(Math.min(Math.max(next, 0), MAX_STAKE_ZEN));
              }}
              className="rounded-xl border border-white/15 bg-slate-900/70 px-3 py-2 text-white outline-none transition focus:border-emerald-400"
            />
            <span className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
              Max per bet: {MAX_STAKE_ZEN} ZEN
            </span>
          </label>
          <div className="flex flex-1 flex-col gap-1 rounded-xl border border-white/10 bg-slate-900/70 p-3 text-sm text-slate-200">
            <div className="flex items-center justify-between">
              <span>FX (ZEN/USD)</span>
              <span className="font-semibold text-white">
                {fx ? fx.zen_usd.toFixed(4) : "loading…"} {fx?.stale ? "(stale)" : ""}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>Profit in USDC</span>
              <span className="font-semibold text-emerald-200">
                {profitUsd !== null ? `${profitUsd.toFixed(4)} USDC` : "—"}
              </span>
            </div>
            <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.2em] text-slate-500">
              <span>Displayed odds</span>
              <span>{quote ? quote.displayed_odds_multiplier.toFixed(3) : "—"}</span>
            </div>
          </div>
        </div>
        {loading && <p className="mt-2 text-xs text-slate-400">Calculating quote…</p>}
        {error && (
          <p className="mt-2 text-xs text-rose-300">
            {error}. Pricing uses live Polymarket odds + Binance FX; if stale, please retry.
          </p>
        )}
      </div>
      <div className="mt-5 rounded-3xl border border-amber-200/30 bg-amber-500/5 p-4 text-sm text-slate-200 sm:p-5">
        <p className="text-base font-semibold text-white">How payouts work</p>
        <p className="mt-2 text-slate-200">
          You deposit ZEN. If you win, you get two tokens:
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-100">
          <li>Your stake back in ZEN minus the platform rake% (rake is charged on the ZEN stake only).</li>
          <li>Your winnings in stable USDC (the profit shown here), keeping gains stable.</li>
        </ul>
      </div>
    </section>
  );
}
