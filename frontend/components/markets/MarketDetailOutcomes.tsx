"use client";
import type { MarketDetail } from "@/lib/api-types";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchPricingQuoteWithMeta, type PricingQuote } from "@/lib/pricing-client";
import { useLiveOutcomePrices } from "@/hooks/useLiveOutcomePrices";
import { seedInitialOutcomes, usePriceStreamStore } from "@/hooks/usePriceStreamConnection";
import { useFxStream } from "@/hooks/useFxStream";
import { useAccount, useChainId, useSwitchChain } from "wagmi";
import { BaseError, type Address } from "viem";
import { buildSignedQuoteParams, useCommitWithQuote } from "@/lib/marketContract";
import { fetchPriceHistory } from "@/lib/pricing-client";

type Props = {
  market: MarketDetail;
};

const DEFAULT_MAX_STAKE_ZEN = 100;

const formatZen = (value: number | undefined): string => {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "—";
  }
  return `${value.toFixed(3)} ZEN`;
};

export function MarketDetailOutcomes({ market }: Props) {
  const outcomes = market.outcomes ?? [];
  const prices = useMemo(() => market.outcomePrices ?? [], [market.outcomePrices]);
  const tokenIds = useMemo(
    () => (Array.isArray(market.clobTokenIds) ? market.clobTokenIds.map((t) => String(t)) : []),
    [market.clobTokenIds],
  );
  const marketStatus = (market.status ?? "").toLowerCase();
  const isResolved = ["resolved", "settled", "cancelled", "canceled", "voided", "closed"].includes(marketStatus);
  const isLocked = ["locked", "disputed"].includes(marketStatus);
  const { prices: livePrices, streamError, fxStale: priceFxStale } = useLiveOutcomePrices(
    market.eventId,
    prices,
    tokenIds,
  );
  const liveStore = usePriceStreamStore(market.eventId, tokenIds);
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
  const fxStaleCombined = fxStale || priceFxStale;
  const tradingHaltedByStream = liveStore.status === "closed" || liveStore.status === "halted";
  const isTradable = !isResolved && !isLocked && !tradingHaltedByStream;
  const { address } = useAccount();
  const chainId = useChainId();
  const { switchChain } = useSwitchChain();
  const { commitWithQuote, isPending: txPending, error: wagmiError } = useCommitWithQuote(
    (market.marketAddress ?? "") as Address,
  );
  const quoteRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
  const maxCapRef = useRef<number>(DEFAULT_MAX_STAKE_ZEN);
  useEffect(() => {
    maxCapRef.current = effectiveMaxStake;
  }, [effectiveMaxStake]);

  const requestQuote = useCallback(
    (_reason: string) => {
      if (quoteRefreshTimer.current) {
        clearTimeout(quoteRefreshTimer.current);
        quoteRefreshTimer.current = null;
      }
      if (!fx || fxStaleCombined || stakeZen <= 0) {
        if (fxStaleCombined) setError("Pricing paused (FX stale)");
        setQuote(null);
        return;
      }
      if (!address || !market.marketAddress) {
        setQuote(null);
        setError("Connect wallet to request a quote");
        return;
      }
      const cappedStake = Math.min(stakeZen, maxCapRef.current);
      if (cappedStake !== stakeZen) {
        setStakeZen(cappedStake);
        setError(`Adjusted stake to cap (${cappedStake.toFixed(3)} ZEN)`);
      }
      setLoading(true);
      fetchPricingQuoteWithMeta(cappedStake, {
        marketId: market.eventId,
        walletAddress: address,
        outcomeId: selectedOutcome,
        marketAddress: market.marketAddress ?? undefined,
      })
        .then((payload) => {
          setQuote(payload);
          setError(null);
        })
        .catch((err) => setError((err as Error).message))
        .finally(() => setLoading(false));
    },
    [fx, fxStaleCombined, stakeZen, address, market.marketAddress, market.eventId, selectedOutcome],
  );

  useEffect(() => {
    requestQuote("init");
    return () => {
      if (quoteRefreshTimer.current) clearTimeout(quoteRefreshTimer.current);
    };
  }, [requestQuote]);

  useEffect(() => {
    if (!quote) return;
    const expiresTs = new Date(quote.expires_at).getTime();
    const now = Date.now();
    if (expiresTs <= now) {
      setError("Quote expired. Refreshing…");
      requestQuote("expired");
      return;
    }
    const refreshInMs = Math.max(500, expiresTs - now - 1500);
    quoteRefreshTimer.current = setTimeout(() => requestQuote("expiry_refresh"), refreshInMs);
    return () => {
      if (quoteRefreshTimer.current) clearTimeout(quoteRefreshTimer.current);
    };
  }, [quote, requestQuote]);

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

  const stakeZenFromQuote =
    typeof quote?.stake_zen === "number" && !Number.isNaN(quote.stake_zen) ? quote.stake_zen : stakeZen;
  const rakeZenValue =
    typeof quote?.rake_zen === "number" && !Number.isNaN(quote.rake_zen) ? quote.rake_zen : null;
  const rakePercent =
    typeof quote?.rake_percent === "number" && !Number.isNaN(quote.rake_percent) ? quote.rake_percent : null;
  const refundZenValue =
    typeof quote?.refund_zen === "number" && !Number.isNaN(quote.refund_zen)
      ? quote.refund_zen
      : rakeZenValue !== null
        ? Math.max(stakeZenFromQuote - rakeZenValue, 0)
        : null;
  const winSummaryLabel = `${refundZenValue !== null && refundZenValue !== undefined && Number.isFinite(refundZenValue) ? refundZenValue.toFixed(3) : "—"} ZEN + ${
    profitUsd !== null && profitUsd !== undefined && Number.isFinite(profitUsd) ? profitUsd.toFixed(3) : "—"
  } USDC`;
  const lastUpdateTs =
    liveStore.lastUpdated ||
    liveStore.outcomes
      .map((o) => o.updatedAt)
      .filter(Boolean)
      .sort()
      .slice(-1)[0];
  const fxBadge = fxStaleCombined ? "FX stale" : fx ? `FX ${fx.zen_usd.toFixed(4)} USD` : "FX connecting";

  // Seed initial prices from streamer history if nothing live has arrived yet.
  useEffect(() => {
    let cancelled = false;
    const hasLive = livePrices.some((p) => typeof p === "number");
    const hasInitial = prices.some((p) => typeof p === "number");
    if (hasLive || hasInitial || outcomes.length === 0) return;
    const load = async () => {
      try {
        const historyPrices: Array<number | undefined> = [];
        for (let i = 0; i < outcomes.length; i += 1) {
          try {
            const history = await fetchPriceHistory(market.eventId, i, 1);
            if (Array.isArray(history) && history.length > 0) {
              const latest = history[0];
              const display = Number(latest.display_price ?? latest.price);
              historyPrices.push(Number.isFinite(display) ? display : undefined);
            } else {
              historyPrices.push(undefined);
            }
          } catch {
            historyPrices.push(undefined);
          }
        }
        if (cancelled) return;
        if (historyPrices.some((p) => typeof p === "number")) {
          seedInitialOutcomes(market.eventId, historyPrices as number[], tokenIds);
        }
      } catch {
        // ignore; history is best-effort
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [livePrices, prices, outcomes.length, market.eventId, tokenIds]);

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
      setTxError("Quote expired. Requesting a fresh quote.");
      requestQuote("expired_commit");
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
    <section className="rounded-3xl border border-white/10 bg-slate-950/50 p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
        <span
          className={`rounded-full px-3 py-1 ${
            liveStore.connected ? "bg-emerald-500/15 text-emerald-100" : "bg-amber-500/15 text-amber-100"
          }`}
        >
          {liveStore.connected ? "Live from streamer" : "Streaming reconnecting"}
        </span>
        {liveStore.transport && (
          <span className="rounded-full bg-white/10 px-3 py-1 text-white/70">Transport {liveStore.transport}</span>
        )}
        {lastUpdateTs && (
          <span className="rounded-full bg-white/10 px-3 py-1 text-white/70">
            Last tick {new Date(lastUpdateTs).toLocaleTimeString()}
          </span>
        )}
        <span
          className={`rounded-full px-3 py-1 ${
            fxStaleCombined ? "bg-amber-500/20 text-amber-100" : "bg-emerald-500/15 text-emerald-100"
          }`}
        >
          {fxBadge}
        </span>
        {streamError && (
          <span className="rounded-full bg-rose-500/15 px-3 py-1 text-rose-100">Stream error: {streamError}</span>
        )}
        {fxStaleCombined && <span className="rounded-full bg-amber-500/15 px-3 py-1 text-amber-100">FX stale</span>}
        {isResolved && <span className="rounded-full bg-rose-500/20 px-3 py-1 text-rose-100">Market resolved</span>}
        {isLocked && !isResolved && (
          <span className="rounded-full bg-amber-500/20 px-3 py-1 text-amber-100">Trading locked</span>
        )}
        {tradingHaltedByStream && !isResolved && (
          <span className="rounded-full bg-rose-500/20 px-3 py-1 text-rose-100">Market closed</span>
        )}
        {liveStore.status && (
          <span
            className={`rounded-full px-3 py-1 ${
              liveStore.status === "halted" || liveStore.status === "closed"
                ? "bg-rose-500/20 text-rose-100"
                : "bg-emerald-500/15 text-emerald-100"
            }`}
          >
            Status: {liveStore.status}
          </span>
        )}
        {liveStore.tickSize && (
          <span className="rounded-full bg-white/10 px-3 py-1 text-white/70">Tick size: {liveStore.tickSize}</span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Tradable outcomes</p>
        <h2 className="text-2xl font-semibold leading-snug text-white">{market.title}</h2>
        <p className="text-sm text-slate-300">
          Expand an outcome to see live odds, bids/asks from the streamer, and trade with ZEN. Winnings pay out as
          ZEN (minus rake) plus USDC profit.
        </p>
        {!isTradable && (
          <p className="text-sm font-semibold text-amber-200">
            Trading is disabled for this market (status: {market.status ?? "unknown"}).
          </p>
        )}
      </div>

      <div className="mt-5 space-y-4">
        {outcomes.map((outcome, idx) => {
          const price =
            typeof livePrices[idx] === "number"
              ? livePrices[idx]
              : typeof prices[idx] === "number"
                ? prices[idx]
                : undefined;
          const probability = price !== undefined ? `${Math.round(price * 100)}%` : "—";
          const outcomeState = liveStore.outcomes[idx] || {};
          const bestBid = outcomeState.bestBid;
          const bestAsk = outcomeState.bestAsk;
          const spread =
            bestBid !== undefined && bestAsk !== undefined && bestAsk > 0
              ? `${(((bestAsk - bestBid) / bestAsk) * 100).toFixed(2)}%`
              : "—";
          const updatedAt =
            outcomeState.updatedAt && !Number.isNaN(Date.parse(outcomeState.updatedAt))
              ? new Date(outcomeState.updatedAt).toLocaleTimeString()
              : null;
          const isSelected = selectedOutcome === idx;

          return (
            <div
              key={`${outcome}-${idx}`}
              className={`overflow-hidden rounded-2xl border transition ${
                isSelected ? "border-emerald-400/60 bg-white/5" : "border-white/10 bg-black/30 hover:border-white/20"
              }`}
            >
              <button
                type="button"
                className="relative flex w-full flex-col gap-3 px-4 py-4 text-left sm:flex-row sm:items-center sm:justify-between"
                onClick={() => {
                  setSelectedOutcome(idx);
                  setTxHash(null);
                  setTxError(null);
                  setError(null);
                }}
              >
                <div className="space-y-1">
                  <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">Outcome</p>
                  <p className="text-lg font-semibold text-white">{outcome}</p>
                  <p className="text-xs text-slate-400">
                    Bid: {bestBid ? bestBid.toFixed(3) : "—"} · Ask: {bestAsk ? bestAsk.toFixed(3) : "—"} · Spread:{" "}
                    {spread}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                  <span className="rounded-full bg-white/10 px-3 py-1 text-white/80">Outcome #{idx + 1}</span>
                  <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-emerald-100">
                    Price {formatZen(price)}
                  </span>
                  <span className="rounded-full bg-white/10 px-3 py-1 text-white/70">
                    <span className="text-white/60">Implied</span>{" "}
                    <span className="font-semibold text-white">{probability}</span>
                  </span>
                  <a
                    href="#trade-panel"
                    className="rounded-full bg-brand-500/20 px-3 py-1 text-white underline-offset-4 transition hover:bg-brand-500/30 hover:underline"
                    aria-label={`Buy ${outcome}`}
                  >
                    Buy {outcome}
                  </a>
                  {outcomeState.status && (
                    <span className="rounded-full bg-white/10 px-3 py-1 text-white/70">
                      Status: {outcomeState.status}
                    </span>
                  )}
                  {updatedAt && (
                    <span className="rounded-full bg-white/5 px-3 py-1 text-white/70">Updated {updatedAt}</span>
                  )}
                  {!isTradable && (
                    <span className="rounded-full bg-rose-500/20 px-3 py-1 text-rose-100">Not tradable</span>
                  )}
                </div>
              </button>

              {isSelected && (
                <div id="trade-panel" className="border-t border-white/10 bg-slate-900/40 px-4 py-4 sm:px-5 sm:py-5">
                  <div className="grid gap-4 lg:grid-cols-[1.25fr,1fr]">
                    <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
                      <div className="flex items-center justify-between">
                        <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Live order signals</p>
                        <span className="rounded-full bg-white/10 px-3 py-1 text-[11px] text-white/80">
                          Stream {liveStore.connected ? "connected" : "connecting"}
                        </span>
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                        <StatTile label="Live price (ZEN)" value={formatZen(price)} />
                        <StatTile label="Best bid" value={bestBid ? `${bestBid.toFixed(3)} ZEN` : "—"} />
                        <StatTile label="Best ask" value={bestAsk ? `${bestAsk.toFixed(3)} ZEN` : "—"} />
                        <StatTile label="Spread" value={spread} />
                        <StatTile label="FX status" value={fxStaleCombined ? "Stale FX" : "Fresh"} />
                      </div>
                      {updatedAt && (
                        <p className="mt-3 text-xs text-slate-400">Last streamer tick: {updatedAt}</p>
                      )}
                    </div>

                    <div className="rounded-2xl border border-white/10 bg-slate-900/70 p-4">
                      <div className="flex items-center justify-between">
                        <h4 className="text-base font-semibold text-white">Trade {outcome}</h4>
                        <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-[11px] font-semibold text-emerald-100">
                          Bets in ZEN
                        </span>
                      </div>
                      {!isTradable && (
                        <p className="mt-2 text-sm text-amber-200">
                          Trading disabled: market is {market.status ?? "closed"}.
                        </p>
                      )}
                      <div className="mt-3 space-y-2">
                        <label className="text-[11px] uppercase tracking-[0.25em] text-slate-500">
                          Stake (ZEN)
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
                            className="mt-1 w-full rounded-xl border border-white/15 bg-slate-900/80 px-3 py-2 text-white outline-none transition focus:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={!isTradable}
                          />
                        </label>
                        <div className="flex flex-wrap gap-2 text-[11px]">
                          {[5, 10, 25, 50].map((preset) => (
                            <button
                              key={preset}
                              type="button"
                              onClick={() => setStakeZen(Math.min(preset, effectiveMaxStake))}
                              className="rounded-full bg-white/10 px-3 py-1 font-semibold uppercase tracking-[0.2em] text-white/80 hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50"
                              disabled={!isTradable}
                            >
                              {preset} ZEN
                            </button>
                          ))}
                          <span className="rounded-full bg-white/5 px-3 py-1 text-white/60">
                            Max per bet: {effectiveMaxStake.toFixed(3)} ZEN
                          </span>
                        </div>
                      </div>

                      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                        <PayoutRow label="Stake" value={`${stakeZenFromQuote.toFixed(3)} ZEN`} />
                        <PayoutRow
                          label="Rake"
                          value={
                            rakeZenValue !== null
                              ? `${rakeZenValue.toFixed(3)} ZEN${rakePercent !== null ? ` (${rakePercent.toFixed(2)}%)` : ""}`
                              : "—"
                          }
                        />
                        <PayoutRow
                          label="Win (ZEN)"
                          value={
                            refundZenValue !== null && refundZenValue !== undefined && Number.isFinite(refundZenValue)
                              ? `${refundZenValue.toFixed(3)} ZEN`
                              : "—"
                          }
                        />
                        <PayoutRow
                          label="Profit (USDC)"
                          highlight
                          value={
                            profitUsd !== null && profitUsd !== undefined && Number.isFinite(profitUsd)
                              ? `${profitUsd.toFixed(3)} USDC`
                              : "—"
                          }
                        />
                      </div>
                      <p className="mt-1 text-xs text-slate-300">Win = {winSummaryLabel}</p>

                      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-slate-500">
                        <span className="rounded-full bg-white/5 px-2 py-1">Quote {quote?.quote_id ?? "pending"}</span>
                        {expiresLabel && <span className="rounded-full bg-white/5 px-2 py-1">{expiresLabel}</span>}
                        {quote?.chain_id && chainId && Number(quote.chain_id) !== chainId && (
                          <span className="rounded-full bg-rose-500/20 px-2 py-1 text-rose-100">
                            Wrong network (expected {quote.chain_id})
                          </span>
                        )}
                        {fxStaleCombined && (
                          <span className="rounded-full bg-amber-500/15 px-2 py-1 text-amber-100">FX stale</span>
                        )}
                        {quote?.remaining_user_stake_zen !== null &&
                          quote?.remaining_user_stake_zen !== undefined && (
                            <span className="rounded-full bg-white/5 px-2 py-1 text-white/70">
                              User cap {quote.remaining_user_stake_zen.toFixed(3)} ZEN
                            </span>
                          )}
                        {quote?.remaining_market_stake_zen !== null &&
                          quote?.remaining_market_stake_zen !== undefined && (
                            <span className="rounded-full bg-white/5 px-2 py-1 text-white/70">
                              Market cap {quote.remaining_market_stake_zen.toFixed(3)} ZEN
                            </span>
                          )}
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          onClick={() => requestQuote("manual_refresh")}
                          className="inline-flex items-center justify-center rounded-full bg-white/10 px-4 py-2 text-sm font-semibold text-white hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={!isTradable}
                        >
                          Refresh quote
                        </button>
                        <button
                          type="button"
                          onClick={handleCommit}
                          disabled={
                            txLoading ||
                            txPending ||
                            !quote ||
                            fxStaleCombined ||
                            !isTradable ||
                            Boolean(quote?.chain_id && chainId && Number(quote.chain_id) !== chainId)
                          }
                          className={`inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] transition ${
                            txLoading ||
                            txPending ||
                            !quote ||
                            fxStaleCombined ||
                            (quote?.chain_id && chainId && Number(quote.chain_id) !== chainId)
                              ? "cursor-not-allowed bg-white/20 text-white/60"
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

                      {quote && (
                        <p className="mt-2 text-[11px] uppercase tracking-[0.2em] text-slate-500">
                          Caps — user:{" "}
                          {quote.remaining_user_stake_zen !== null && quote.remaining_user_stake_zen !== undefined
                            ? `${quote.remaining_user_stake_zen.toFixed(3)} ZEN`
                            : "n/a"}
                          , market:{" "}
                          {quote.remaining_market_stake_zen !== null && quote.remaining_market_stake_zen !== undefined
                            ? `${quote.remaining_market_stake_zen.toFixed(3)} ZEN`
                            : "n/a"}
                          {" · "}Max bet (API):{" "}
                          {quote.max_stake_zen !== null && quote.max_stake_zen !== undefined
                            ? `${quote.max_stake_zen.toFixed(3)} ZEN`
                            : `${DEFAULT_MAX_STAKE_ZEN} ZEN`}
                          {quote.chain_id && chainId && Number(quote.chain_id) !== chainId && switchChain && (
                            <button
                              type="button"
                              className="ml-2 rounded-full bg-white/10 px-2 py-1 text-xs font-semibold text-white hover:bg-white/20"
                              onClick={() => switchChain({ chainId: Number(quote.chain_id) })}
                            >
                              Switch network
                            </button>
                          )}
                        </p>
                      )}
                      {loading && <p className="mt-2 text-xs text-slate-400">Calculating quote…</p>}
                      {error && (
                        <p className="mt-2 text-xs text-rose-300">
                          {error}. Pricing uses live odds + FX from the streamer; if stale, retry.
                        </p>
                      )}
                      {(txError || wagmiError) && (
                        <p className="mt-1 text-xs text-rose-300">
                          {txError ??
                            (wagmiError instanceof BaseError
                              ? wagmiError.shortMessage
                              : wagmiError instanceof Error
                                ? wagmiError.message
                                : "Transaction failed")}
                          . Ensure chain and quote are valid.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-6 rounded-3xl border border-amber-200/30 bg-amber-500/5 p-4 text-sm text-slate-200 sm:p-5">
        <p className="text-base font-semibold text-white">How payouts work</p>
        <p className="mt-2 text-slate-200">
          You deposit ZEN. If you win, you receive two pieces: your ZEN stake back minus the rake fee, plus the USDC
          profit shown above. Losses forfeit the staked ZEN.
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-100">
          <li>All bets are denominated in ZEN; rake is charged on the ZEN stake.</li>
          <li>Profit settles in USDC to keep upside stable while you get your (rake-adjusted) ZEN back.</li>
          <li>Live odds, bids, and asks stream from the streamer (WS/SSE) used by the backend.</li>
        </ul>
      </div>
    </section>
  );
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-2">
      <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-white">{value}</p>
    </div>
  );
}

function PayoutRow({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/60 px-3 py-2">
      <p className="text-[11px] uppercase tracking-[0.25em] text-slate-500">{label}</p>
      <p className={`text-sm font-semibold ${highlight ? "text-emerald-200" : "text-white"}`}>{value}</p>
    </div>
  );
}
