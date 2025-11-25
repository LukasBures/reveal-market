 "use client";

import Link from "next/link";
import type { MarketDetail } from "@/lib/api-types";
import { useEffect, useMemo, useState } from "react";
import { fetchPricingQuoteWithMeta, type PricingQuote } from "@/lib/pricing-client";
import { OutcomeQuote } from "./OutcomeQuote";
import { useLiveOutcomePrices } from "@/hooks/useLiveOutcomePrices";
import { usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { useFxStream } from "@/hooks/useFxStream";
import { useAccount, useChainId } from "wagmi";
import type { Address } from "viem";
import { buildSignedQuoteParams, useCommitWithQuote } from "@/lib/marketContract";

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
  const { prices: livePrices, streamError } = useLiveOutcomePrices(market.eventId, prices);
  const liveStore = usePriceStreamStore(market.eventId);
  const [selectedOutcome, setSelectedOutcome] = useState(0);
  const [stakeZen, setStakeZen] = useState(10);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [txError, setTxError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [txLoading, setTxLoading] = useState(false);
  const { fx, status } = useFxStream("/fx/zen-usdc");
  const fxStale = status === "stale";
  const { address } = useAccount();
  const chainId = useChainId();
  const { commitWithQuote, isPending: txPending, error: wagmiError } = useCommitWithQuote(
    (market.marketAddress ?? "") as Address,
  );

  useEffect(() => {
    if (!fx || fxStale || stakeZen <= 0) {
      if (fxStale) setError("Pricing paused (FX stale)");
      setQuote(null);
      return;
    }
    if (!address || !market.marketAddress) {
      setQuote(null);
      setError("Connect wallet to request a quote");
      return;
    }
    if (stakeZen > MAX_STAKE_ZEN) {
      setQuote(null);
      setError(`Max stake per bet is ${MAX_STAKE_ZEN} ZEN`);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchPricingQuoteWithMeta(stakeZen, {
      marketId: market.eventId,
      walletAddress: address,
      outcomeId: selectedOutcome,
      marketAddress: market.marketAddress ?? undefined,
    })
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
  }, [fx, fxStale, stakeZen, market.eventId, address, market.marketAddress, selectedOutcome]);

  const profitUsd = useMemo(() => {
    if (!quote) return null;
    return quote.hedge_usdc * quote.displayed_odds_multiplier - quote.hedge_usdc;
  }, [quote]);

  const expiresLabel = useMemo(() => {
    if (!quote) return null;
    const expiresTs = new Date(quote.expires_at).getTime();
    const remainingMs = expiresTs - Date.now();
    if (remainingMs <= 0) return "Expired";
    const seconds = Math.ceil(remainingMs / 1000);
    return `Quote expires in ${seconds}s`;
  }, [quote]);

  async function handleCommit() {
    setTxError(null);
    setTxHash(null);
    if (!address) {
      setTxError("Connect wallet before committing.");
      return;
    }
    if (!market.marketAddress) {
      setTxError("Market contract address missing.");
      return;
    }
    if (!quote) {
      setTxError("Request a quote first.");
      return;
    }
    if (stakeZen !== quote.stake_zen) {
      setTxError("Stake changed. Refresh the quote.");
      return;
    }
    // Quote must still be live and chain-aligned before submitting the tx.
    const expiresTs = new Date(quote.expires_at).getTime();
    if (expiresTs <= Date.now()) {
      setTxError("Quote expired. Request a new one.");
      return;
    }
    if (quote.chain_id && chainId && Number(quote.chain_id) !== chainId) {
      setTxError(`Switch to chain ${quote.chain_id} to commit.`);
      return;
    }
    try {
      setTxLoading(true);
      const params = buildSignedQuoteParams({
        quote,
        outcomeId: selectedOutcome,
        walletAddress: address as Address,
        amountWei: BigInt(quote.stake_wei),
      });
      const tx = await commitWithQuote(params);
      setTxHash(typeof tx === "string" ? tx : (tx as any)?.hash ?? null);
    } catch (err) {
      setTxError((err as Error).message);
    } finally {
      setTxLoading(false);
    }
  }

  if (outcomes.length === 0) {
    return (
      <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-slate-400">
        No outcome data available.
      </div>
    );
  }

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/40 p-4 sm:p-6">
      {(fxStale || streamError) && (
        <div className="mb-3 rounded-2xl border border-amber-300/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          Live pricing paused{fxStale ? " (FX stale)" : ""}{streamError ? ` (${streamError})` : ""}. Actions are
          temporarily disabled.
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span
          className={`rounded-full px-2 py-1 ${
            liveStore.status === "halted" || liveStore.status === "closed"
              ? "bg-rose-500/20 text-rose-100"
              : "bg-emerald-500/15 text-emerald-100"
          }`}
        >
          Status: {liveStore.status ?? "open"}
        </span>
        {liveStore.tickSize && (
          <span className="rounded-full bg-white/10 px-2 py-1 text-white/70">Tick size: {liveStore.tickSize}</span>
        )}
      </div>
      {quote && (
        <p className="mt-2 text-[11px] uppercase tracking-[0.2em] text-slate-400">
          Quote ID: {quote.quote_id} · {expiresLabel}
        </p>
      )}
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
      <OutcomeQuote
        stakeZen={10}
        marketId={market.eventId}
        marketAddress={market.marketAddress}
        outcomeId={selectedOutcome}
      />
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
              const price = typeof livePrices[idx] === "number" ? livePrices[idx] : undefined;
              const probability = price !== undefined ? `${Math.round(price * 100)}%` : "—";
              const href = `/markets/${market.eventId}?outcome=${encodeURIComponent(String(idx))}`;
              const isYes = idx === 0;
              const isNo = idx === 1;
              const outcomeState = liveStore.outcomes[idx] || {};
              const bestBid = outcomeState.bestBid;
              const bestAsk = outcomeState.bestAsk;
              const spread =
                bestBid !== undefined && bestAsk !== undefined && bestAsk > 0
                  ? `${(((bestAsk - bestBid) / bestAsk) * 100).toFixed(2)}%`
                  : "—";
              return (
                <tr key={outcome} className="border-t border-white/5">
                  <td className="py-3 font-semibold text-white">{outcome}</td>
                  <td className="py-3 text-slate-300">{probability}</td>
                  <td className="py-3 text-slate-300">
                    <div className="flex flex-col gap-1">
                      <span>{formatZen(price)}</span>
                      <span className="text-xs text-slate-400">
                        Bid: {bestBid ? bestBid.toFixed(3) : "—"} · Ask: {bestAsk ? bestAsk.toFixed(3) : "—"} · Spread:{" "}
                        {spread}
                      </span>
                    </div>
                  </td>
                  <td className="py-3 text-right">
                    <Link
                      href={`/markets/${market.eventId}?outcome=${encodeURIComponent(String(idx))}`}
                      className={`inline-flex w-full sm:w-[180px] items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] text-white transition ${
                        isYes
                          ? "bg-emerald-500 hover:bg-emerald-400"
                          : isNo
                            ? "bg-rose-500 hover:bg-rose-400"
                            : "bg-white/20 hover:bg-white/30"
                      } ${fxStale ? "pointer-events-none opacity-60" : ""}`}
                      aria-disabled={fxStale}
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
                {fx && fx.zen_usd > 0 ? fx.zen_usd.toFixed(2) : "0.00"} {fx?.stale ? "(stale)" : ""}
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
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-slate-400">
            {expiresLabel ? `Quote ID ${quote?.quote_id ?? ""} · ${expiresLabel}` : "Request a quote to trade"}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCommit}
              disabled={txLoading || txPending || !quote || fxStale}
              className={`inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] transition ${
                txLoading || txPending || !quote || fxStale
                  ? "bg-white/20 text-white/60 cursor-not-allowed"
                  : "bg-emerald-500 text-white hover:bg-emerald-400"
              }`}
            >
              {txLoading || txPending ? "Submitting…" : "Commit with quote"}
            </button>
            {txHash && (
              <span className="text-[11px] text-emerald-200">
                Submitted tx: {txHash.slice(0, 10)}…{txHash.slice(-6)}
              </span>
            )}
          </div>
        </div>
        {loading && <p className="mt-2 text-xs text-slate-400">Calculating quote…</p>}
        {quote && (
          <p className="mt-2 text-[11px] uppercase tracking-[0.2em] text-slate-500">
            Remaining caps — user:{" "}
            {quote.remaining_user_stake_zen !== null && quote.remaining_user_stake_zen !== undefined
              ? `${quote.remaining_user_stake_zen.toFixed(3)} ZEN`
              : "n/a"}
            , market:{" "}
            {quote.remaining_market_stake_zen !== null && quote.remaining_market_stake_zen !== undefined
              ? `${quote.remaining_market_stake_zen.toFixed(3)} ZEN`
              : "n/a"}
          </p>
        )}
        {error && (
          <p className="mt-2 text-xs text-rose-300">
            {error}. Pricing uses live Polymarket odds + Binance FX; if stale, please retry.
          </p>
        )}
        {(txError || wagmiError) && (
          <p className="mt-1 text-xs text-rose-300">
            {txError ?? wagmiError?.message ?? "Transaction failed"}. Ensure chain and quote are valid.
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
