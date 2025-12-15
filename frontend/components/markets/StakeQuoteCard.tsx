"use client";

import { useEffect, useMemo, useState } from "react";
import {
  fetchPricingQuoteWithMeta,
  FX_DEFAULT_PATH,
  type PricingQuote,
  submitTrade,
  type TradeCommitResponse,
} from "@/lib/pricing-client";
import { fetchTradeStatus } from "@/lib/api";
import { useFxStream } from "@/hooks/useFxStream";
import { useAccount, useChainId } from "wagmi";
import { formatTime } from "@/lib/formatters";
import { defaultChain } from "@/lib/wagmi";

type Props = {
  defaultStakeZen?: number;
  marketAddress?: string | null;
  marketId?: string;
  outcomes?: string[];
  initialOutcomeId?: number;
  outcomePrices?: number[];
  marketTitle?: string;
  marketStatus?: string | null;
  isResolved?: boolean | null;
  tradingHalted?: boolean | null;
  initialTxHash?: string | null;
};

const PER_BET_CAP_ZEN = 0.1;
const MIN_STAKE_ZEN = 0.01;
const STAKE_RANGE_ERROR = `Enter between ${MIN_STAKE_ZEN} and ${PER_BET_CAP_ZEN} ZEN (per bet cap)`;
const QUOTE_REFRESH_INTERVAL_MS = 10_000;

const getQuoteExpiryMs = (value: PricingQuote | null): number | null => {
  if (!value) return null;
  const { expiry_ts, expires_at } = value;
  if (typeof expiry_ts === "number" && Number.isFinite(expiry_ts) && expiry_ts > 0) {
    return expiry_ts * 1000;
  }
  if (expires_at) {
    const parsed = Date.parse(expires_at);
    return Number.isNaN(parsed) ? null : parsed;
  }
  return null;
};

const formatNumber = (value: number, decimals = 4) => {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(decimals);
};

export function StakeQuoteCard({
  defaultStakeZen = PER_BET_CAP_ZEN,
  marketAddress,
  marketId,
  outcomes = [],
  initialOutcomeId = 0,
  outcomePrices = [],
  marketTitle,
  marketStatus,
  isResolved,
  tradingHalted = null,
  initialTxHash = null,
}: Props) {
  const [stakeZen, setStakeZen] = useState<number>(defaultStakeZen);
  const [stakeInput, setStakeInput] = useState<string>(defaultStakeZen.toFixed(2));
  const [stakeError, setStakeError] = useState<string | null>(null);
  const [selectedOutcome, setSelectedOutcome] = useState<number>(initialOutcomeId);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const { fx, status, fxReceivedAt, ageSeconds } = useFxStream(FX_DEFAULT_PATH);
  const fxStale = status === "stale";
  const fxLive = status === "live" && !fx?.stale;
  const { address } = useAccount();
  const chainId = useChainId();
  const expectedChainId = defaultChain.id;
  const chainMismatch = Boolean(chainId && chainId !== expectedChainId);
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(initialTxHash);
  const [txConfirmed, setTxConfirmed] = useState(false);
  const [txStatus, setTxStatus] = useState<string | null>(null);
  const explorerBase =
    (process.env.NEXT_PUBLIC_EXPLORER_BASE_URL ?? "https://horizen-testnet.explorer.caldera.xyz/tx").replace(/\/+$/, "");
  const txPending = false;
  const [quoteCountdown, setQuoteCountdown] = useState<string | null>(null);
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
      PER_BET_CAP_ZEN,
      quote?.max_stake_zen ?? null,
      quote?.remaining_user_stake_zen ?? null,
      quote?.remaining_market_stake_zen ?? null,
      quote?.max_user_stake_per_market_zen ?? null,
      quote?.max_market_stake_zen ?? null,
    ]
      .filter((v): v is number => v !== null && v !== undefined && !Number.isNaN(v))
      .map((v) => Math.max(0, v));
    if (!caps.length) return PER_BET_CAP_ZEN;
    const minCap = Math.min(...caps);
    return Math.max(0, Math.min(PER_BET_CAP_ZEN, minCap));
  }, [quote]);
  const capExhausted = effectiveMaxStake <= 0;
  const fxAgeSeconds = useMemo(() => {
    if (typeof ageSeconds === "number") return Math.max(0, ageSeconds);
    if (fxReceivedAt) return Math.max(0, (Date.now() - Date.parse(fxReceivedAt)) / 1000);
    return null;
  }, [ageSeconds, fxReceivedAt]);
  const quoteExpiryMs = useMemo(() => getQuoteExpiryMs(quote), [quote]);

  useEffect(() => {
    if (selectedOutcome >= outcomeOptions.length) {
      setSelectedOutcome(0);
    }
  }, [outcomeOptions, selectedOutcome]);

  const statusNormalized = (marketStatus ?? "").toLowerCase();
  const settledStates = ["settled", "resolved", "closed", "cancelled", "canceled", "voided"];
  const lockedStates = ["locked", "disputed"];
  const isSettled = isResolved === true || settledStates.includes(statusNormalized);
  const isLocked = lockedStates.includes(statusNormalized);
  const missingMarketAddress = !marketAddress;
  const allowAutoCreate = missingMarketAddress && Boolean(marketId);
  const tradingBlocked = Boolean(tradingHalted || isSettled || isLocked);
  const missingAddressBlocking = missingMarketAddress && !allowAutoCreate;
  const tradingDisabled = tradingBlocked || missingAddressBlocking;
  const tradingReason = tradingHalted
    ? "Trading halted"
    : isSettled
      ? "Market settled"
      : isLocked
        ? "Market locked"
        : missingAddressBlocking
          ? "Market address unavailable"
          : null;

  useEffect(() => {
    let cancelled = false;
    const requestQuote = async () => {
      if (tradingDisabled) {
        setQuote(null);
        setError(tradingReason ?? "Trading disabled");
        return;
      }
      if (!address) {
        setQuote(null);
        setError("Connect wallet to request a quote");
        return;
      }
      if (!marketId) {
        setQuote(null);
        setError("Market unavailable (missing id)");
        return;
      }
      if (!chainId || chainMismatch) {
        setQuote(null);
        setError(`Switch to ${defaultChain.name} to trade`);
        return;
      }
      if (debouncedStake < MIN_STAKE_ZEN) {
        setQuote(null);
        setError(STAKE_RANGE_ERROR);
        return;
      }
      if (capExhausted) {
        setQuote(null);
        setError("Stake cap exhausted for this market/user");
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
          marketAddress: marketAddress ?? "",
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
  }, [
    debouncedStake,
    fx,
    address,
    marketAddress,
    marketId,
    selectedOutcome,
    fxUnavailable,
    refreshNonce,
    effectiveMaxStake,
    tradingDisabled,
    tradingReason,
    chainId,
    chainMismatch,
    capExhausted,
  ]);

  useEffect(() => {
    if (!address || !marketId || tradingDisabled || fxUnavailable || chainMismatch) return;
    const timer = setInterval(() => {
      setRefreshNonce((prev) => prev + 1);
    }, QUOTE_REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [address, marketId, tradingDisabled, fxUnavailable, chainMismatch]);

  useEffect(() => {
    if (!quote) {
      setQuoteCountdown(null);
      return;
    }
    if (!quoteExpiryMs) {
      setQuoteCountdown(null);
      return;
    }
    const expires = quoteExpiryMs;
    const updateCountdown = () => {
      const remainingMs = expires - Date.now();
      if (remainingMs <= 0) {
        setQuoteCountdown("Expired");
        setQuote(null);
        setRefreshNonce((prev) => prev + 1);
        return false;
      }
      const seconds = Math.ceil(remainingMs / 1000);
      setQuoteCountdown(`${seconds}s`);
      return true;
    };
    const ok = updateCountdown();
    if (!ok) return;
    const timer = setInterval(() => {
      const alive = updateCountdown();
      if (!alive) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [quote, quoteExpiryMs]);

  useEffect(() => {
    // Clear quotes on account or chain changes to avoid reusing stale signatures.
    setQuote(null);
    setRefreshNonce((prev) => prev + 1);
    if (!initialTxHash) {
      setTxHash(null);
    }
    setTxConfirmed(false);
    setTxStatus(null);
  }, [chainId, address, initialTxHash]);

  const profitUsd = useMemo(() => {
    if (!quote) return null;
    return quote.hedge_usdc * quote.displayed_odds_multiplier - quote.hedge_usdc;
  }, [quote]);
  const profitZen = useMemo(() => {
    if (!quote) return null;
    if (profitUsd === null) return null;
    const fx = Number(quote.zen_usd);
    if (!Number.isFinite(fx) || fx <= 0) return null;
    return profitUsd / fx;
  }, [profitUsd, quote]);
  const toWinZen = useMemo(() => {
    if (!quote) return null;
    const fx = quote.zen_usd;
    const profitZen = profitUsd !== null && fx ? profitUsd / fx : null;
    const baseStake = Number.isFinite(quote.stake_zen) ? quote.stake_zen : null;
    if (baseStake === null) return null;
    return profitZen !== null ? baseStake + profitZen : baseStake;
  }, [profitUsd, quote]);
  const stakeDisplay = Number.isFinite(stakeZen) && stakeZen > 0 ? `${stakeZen.toFixed(2)} ZEN` : null;
  const ctaLabel = loading
    ? "Pricing…"
    : `Buy ${outcomeLabel}${stakeDisplay ? ` with ${stakeDisplay}` : ""}`;

  const highlightClass =
    selectedOutcome === 0
      ? "shadow-[0_20px_60px_rgba(16,185,129,0.25)] ring-1 ring-emerald-400/30"
      : "shadow-[0_20px_60px_rgba(244,63,94,0.25)] ring-1 ring-rose-400/30";
  const quoteExpired = quote ? (quoteExpiryMs ? quoteExpiryMs <= Date.now() : true) : false;
  const stakeOutOfRange =
    !Number.isFinite(stakeZen) || stakeZen < MIN_STAKE_ZEN || stakeZen > effectiveMaxStake || capExhausted;
  const submitBlockedReason =
    tradingReason ??
    (chainMismatch ? `Switch to ${defaultChain.name}` : null) ??
    (capExhausted ? "Stake cap reached" : null) ??
    (stakeOutOfRange ? STAKE_RANGE_ERROR : null) ??
    (fxUnavailable ? "FX unavailable" : null) ??
    (fxStale ? "FX stale" : null) ??
    (quoteExpired ? "Quote expired" : null) ??
    null;

  const handleTrade = async () => {
    setTxError(null);
    setTxHash(null);
    setTxConfirmed(false);
    if (tradingDisabled) {
      setTxError(tradingReason ?? "Trading disabled");
      return;
    }
    if (!address) {
      setError("Connect wallet to request a quote");
      setTxError("Connect wallet before trading.");
      return;
    }
    if (!marketId) {
      setTxError("Market id missing.");
      return;
    }
    if (!quote) {
      setError("Requesting quote before trading…");
      setRefreshNonce((prev) => prev + 1);
      return;
    }
    if (capExhausted) {
      setTxError("Stake cap reached for this market/user.");
      return;
    }
    if (stakeOutOfRange) {
      setTxError(STAKE_RANGE_ERROR);
      return;
    }
    if (stakeZen !== quote.stake_zen) {
      setTxError("Stake changed. Refresh the quote.");
      return;
    }
    if (!quote.quote_id) {
      setTxError("Quote unavailable. Refreshing…");
      setRefreshNonce((prev) => prev + 1);
      return;
    }
    const expiresTs = quoteExpiryMs;
    if (!expiresTs || expiresTs <= Date.now()) {
      setTxError("Quote expired. Refreshing…");
      setRefreshNonce((prev) => prev + 1);
      return;
    }
    if (quote.chain_id && chainId && Number(quote.chain_id) !== chainId) {
      setTxError(`Switch to chain ${quote.chain_id} to trade.`);
      return;
    }
    if (!chainId || chainMismatch) {
      setTxError(`Switch to ${defaultChain.name} to trade.`);
      return;
    }
    if (fxStale || fxUnavailable || !fxLive) {
      setTxError("FX is stale or unavailable; retry once fresh.");
      return;
    }
    setTxLoading(true);
    try {
      const resp: TradeCommitResponse = await submitTrade(quote.quote_id);
      if (resp.tx_hash) {
        setTxHash(resp.tx_hash);
        setTxStatus(resp.relayer_status ?? null);
        setTxConfirmed(true);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Trade failed";
      const normalized = message.toLowerCase();
      if (normalized.includes("expired")) {
        setTxError("Quote expired. Refreshing…");
        setRefreshNonce((prev) => prev + 1);
      } else if (normalized.includes("consume") || normalized.includes("used") || normalized.includes("replay")) {
        setTxError("Quote already consumed. Requesting a new one.");
        setRefreshNonce((prev) => prev + 1);
      } else {
        setTxError(message);
      }
    } finally {
      setTxLoading(false);
    }
  };

  // Poll transaction status if we have a hash/job id.
  useEffect(() => {
    if (!txHash) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const statusResp = await fetchTradeStatus(txHash);
        if (!cancelled) {
          setTxStatus(statusResp.status);
          if (statusResp.status === "confirmed" || statusResp.status === "failed") {
            setTxConfirmed(statusResp.status === "confirmed");
            return;
          }
        }
      } catch {
        // best effort
      }
      if (!cancelled) {
        setTimeout(poll, 5000);
      }
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [txHash]);

  return (
    <div
      className={`md:sticky md:top-40 self-start rounded-3xl border border-white/10 bg-slate-950/80 p-5 text-sm text-slate-100 backdrop-blur ${highlightClass}`}
    >
      {marketTitle && (
        <p className="text-sm font-semibold text-white/90">{marketTitle}</p>
      )}
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-lg font-semibold text-white">Buy {outcomeLabel}</p>
        </div>
        <div className="flex flex-col items-end gap-2 text-[11px] uppercase tracking-[0.2em]">
          {quote && (
            <span className="rounded-full bg-white/10 px-3 py-1 text-white/80">
              Quote {quote.quote_id ? `${quote.quote_id.slice(0, 6)}…` : "—"} expires{" "}
              {quoteCountdown ?? formatTime(quote.expires_at ?? quoteExpiryMs ?? undefined)}
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
              const formattedPrice = price !== null ? `${Math.round(price * 100)}%` : "—";
              const active = selectedOutcome === idx;
              const isYes = idx === 0;
              return (
                <button
                  key={`${label}-${idx}`}
                  type="button"
                  onClick={() => setSelectedOutcome(idx)}
                  disabled={tradingDisabled}
                  className={`flex flex-col gap-1 rounded-2xl border px-4 py-3 text-left transition ${
                    active
                      ? isYes
                        ? "border-emerald-400 bg-emerald-500/15 text-white"
                        : "border-rose-400 bg-rose-500/15 text-white"
                      : "border-white/10 bg-white/5 text-white/80 hover:border-white/30 hover:bg-white/10"
                  } ${tradingDisabled ? "cursor-not-allowed opacity-60" : ""}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold uppercase tracking-[0.25em]">Buy {label}</span>
                    <span
                      className={`text-sm font-semibold ${
                        active ? (isYes ? "text-emerald-200" : "text-rose-200") : "text-emerald-200"
                      }`}
                    >
                      {formattedPrice}
                    </span>
                  </div>
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
                disabled={tradingDisabled}
                className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] transition ${
                  selectedOutcome === idx ? "bg-white text-slate-900" : "bg-white/10 text-white/80 hover:bg-white/20"
                } ${tradingDisabled ? "cursor-not-allowed opacity-60" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 space-y-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-[0.2em] text-slate-500">Buy with ZEN</span>
          <input
            type="number"
            min={0}
            max={effectiveMaxStake}
            step="0.01"
            value={stakeInput}
            onFocus={() => {
              if (stakeInput === "0" || stakeInput === "0.00") {
                setStakeInput("");
              }
            }}
            disabled={tradingDisabled}
            onChange={(e) => {
              const raw = e.target.value;
              const normalized = raw.replace(",", ".");
              const pattern = /^\d*(?:\.\d{0,2})?$/;
              if (normalized !== "" && !pattern.test(normalized)) {
                return;
              }
              setStakeInput(raw);
              if (normalized === "") {
                setStakeZen(0);
                setStakeError(STAKE_RANGE_ERROR);
                return;
              }
              const next = Number(normalized);
              if (Number.isNaN(next)) {
                setStakeZen(0);
                setStakeError(STAKE_RANGE_ERROR);
                return;
              }
              const rounded = Math.round(next * 100) / 100;
              const capped = Math.min(Math.max(rounded, 0), effectiveMaxStake);
              setStakeZen(capped);
              if (capped < MIN_STAKE_ZEN || capped > effectiveMaxStake) {
                setStakeError(STAKE_RANGE_ERROR);
              } else {
                setStakeError(null);
              }
            }}
            onBlur={() => {
              const normalized = stakeInput.replace(",", ".");
              const next = Number(normalized);
              if (Number.isNaN(next)) {
                setStakeInput("0.00");
                setStakeZen(0);
                setStakeError(STAKE_RANGE_ERROR);
                return;
              }
              const rounded = Math.round(next * 100) / 100;
              const capped = Math.min(Math.max(rounded, 0), effectiveMaxStake);
              setStakeZen(capped);
              setStakeInput(capped.toFixed(2));
              if (capped < MIN_STAKE_ZEN || capped > effectiveMaxStake) {
                setStakeError(STAKE_RANGE_ERROR);
              } else {
                setStakeError(null);
              }
            }}
            className={`w-full rounded-xl border border-white/15 bg-slate-900/80 px-3 py-2 text-white outline-none transition focus:border-emerald-400 ${tradingDisabled ? "cursor-not-allowed opacity-60" : ""}`}
            inputMode="decimal"
            aria-label="Stake in ZEN"
            placeholder="0.00 ZEN"
          />
          <div className="grid grid-cols-3 gap-2 text-[11px] text-slate-500">
            {[MIN_STAKE_ZEN, PER_BET_CAP_ZEN / 2, PER_BET_CAP_ZEN].map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => {
                  const capped = Math.min(preset, effectiveMaxStake);
                  setStakeZen(capped);
                  setStakeInput(capped.toFixed(2));
                  if (capped < MIN_STAKE_ZEN || capped > effectiveMaxStake) {
                    setStakeError(STAKE_RANGE_ERROR);
                  } else {
                    setStakeError(null);
                  }
                }}
                disabled={tradingDisabled}
                className={`w-full rounded-full bg-white/5 px-3 py-1 text-center font-semibold uppercase tracking-[0.2em] text-white/80 hover:bg-white/15 ${tradingDisabled ? "cursor-not-allowed opacity-60" : ""}`}
              >
                {preset} ZEN
              </button>
            ))}
          </div>
        </label>
        <div className="grid grid-cols-1 gap-3 text-xs">
          <Metric label="To win" value={`${formatNumber(toWinZen ?? NaN, 2)} ZEN`} highlight />
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-2">
        {tradingDisabled && (
          <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
            {tradingReason ?? "Trading is unavailable for this market."}
          </div>
        )}
        {quote && (
          <p className="text-xs text-slate-300">
            Stake {formatNumber(quote.stake_zen, 3)} ZEN → Win {formatNumber(toWinZen ?? NaN, 3)} ZEN
          </p>
        )}
        <button
          type="button"
          disabled={
            loading ||
            fxStale ||
            fxUnavailable ||
            !fxLive ||
            !marketId ||
            !address ||
            stakeOutOfRange ||
            tradingDisabled ||
            capExhausted ||
            chainMismatch ||
            txLoading ||
            txPending ||
            quoteExpired
          }
          onClick={handleTrade}
          className={`inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] transition ${
            loading ||
            fxStale ||
            fxUnavailable ||
            !fxLive ||
            !address ||
            tradingDisabled ||
            capExhausted ||
            chainMismatch ||
            txLoading ||
            txPending ||
            quoteExpired
              ? "cursor-not-allowed bg-white/20 text-white/60"
              : "bg-emerald-500 text-white hover:bg-emerald-400"
          }`}
        >
          {submitBlockedReason ?? (txLoading || txPending ? "Submitting…" : ctaLabel)}
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
        {txError && <p className="text-xs text-rose-300">{txError}</p>}
        {stakeError && <p className="text-xs text-rose-300">{stakeError}</p>}
        {fxStale && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-300">
            Pricing paused due to stale FX. Please retry in a moment.
          </p>
        )}
        {capExhausted && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-200">
            Stake cap reached for this market/user. Try again later.
          </p>
        )}
        {chainMismatch && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-200">
            Switch to {defaultChain.name} (chain {expectedChainId}) to trade.
          </p>
        )}
        {txHash && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-200">
            Commit tx:{" "}
            <a
              href={`${explorerBase}/${txHash}`}
              target="_blank"
              rel="noreferrer"
              className="underline decoration-dotted"
            >
              {txHash.slice(0, 10)}…{txHash.slice(-6)}
            </a>{" "}
            ({txStatus ?? "pending"})
          </p>
        )}
        {txConfirmed && txHash && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-200">
            Commit confirmed on-chain.
          </p>
        )}
      </div>
      {quote && (
        <div className="mt-4 rounded-2xl border border-white/10 bg-slate-900/60 p-3 text-xs text-slate-300">
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">Trade summary</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <span>Stake: {formatNumber(quote.stake_zen, 3)} ZEN</span>
            <span>Refund: {formatNumber(quote.refund_zen, 3)} ZEN</span>
            <span>Profit: {formatNumber(profitZen ?? NaN, 3)} ZEN</span>
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
