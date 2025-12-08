"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchPricingQuoteWithMeta, type PricingQuote } from "@/lib/pricing-client";
import { useFxStream } from "@/hooks/useFxStream";
import { useAccount, useChainId, usePublicClient, useReadContract, useWriteContract } from "wagmi";
import { formatTime } from "@/lib/formatters";
import { ZEN_TOKEN_ADDRESS } from "@/lib/tokens";
import { erc20Abi, maxUint256, type Address, type Hex } from "viem";
import { buildSignedQuoteParams, useCommitWithQuote } from "@/lib/marketContract";

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
};

const DEFAULT_MAX_STAKE_ZEN = 10.0;
const MIN_STAKE_ZEN = 0.1;
const MAX_STAKE_ZEN = 10.0;
const STAKE_RANGE_ERROR = `Enter between ${MIN_STAKE_ZEN} and ${MAX_STAKE_ZEN} ZEN`;

const formatNumber = (value: number, decimals = 4) => {
  if (!Number.isFinite(value)) return "—";
  return value.toFixed(decimals);
};

export function StakeQuoteCard({
  defaultStakeZen = 1,
  marketAddress,
  marketId,
  outcomes = [],
  initialOutcomeId = 0,
  outcomePrices = [],
  marketTitle,
  marketStatus,
  isResolved,
  tradingHalted = null,
}: Props) {
  const [stakeZen, setStakeZen] = useState<number>(defaultStakeZen);
  const [stakeInput, setStakeInput] = useState<string>(defaultStakeZen.toFixed(2));
  const [stakeError, setStakeError] = useState<string | null>(null);
  const [selectedOutcome, setSelectedOutcome] = useState<number>(initialOutcomeId);
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const { fx, status } = useFxStream("/fx/zen-usdc");
  const fxStale = status === "stale";
  const fxLive = status === "live" && !fx?.stale;
  const { address } = useAccount();
  const chainId = useChainId();
  const { commitWithQuote, isPending: txPending, error: commitError } = useCommitWithQuote(
    (marketAddress ?? "") as Address,
  );
  const publicClient = usePublicClient({ chainId });
  const {
    writeContractAsync: writeApprovalAsync,
    error: approvalError,
  } = useWriteContract();
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(null);
  const [approvalHash, setApprovalHash] = useState<Hex | null>(null);
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
    return Math.max(MIN_STAKE_ZEN, Math.min(...caps));
  }, [quote]);

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
  const tradingDisabled = Boolean(tradingHalted || isSettled || isLocked);
  const tradingReason = tradingHalted
    ? "Trading halted"
    : isSettled
      ? "Market settled"
      : isLocked
        ? "Market locked"
        : null;
  const missingZenToken = !ZEN_TOKEN_ADDRESS;
  const allowanceEnabled = Boolean(address && marketAddress && ZEN_TOKEN_ADDRESS);
  const {
    data: allowance,
    isFetching: allowanceLoading,
    refetch: refetchAllowance,
  } = useReadContract({
    address: allowanceEnabled ? (ZEN_TOKEN_ADDRESS as Address) : undefined,
    abi: erc20Abi,
    functionName: "allowance",
    args: allowanceEnabled ? ([address as Address, marketAddress as Address] as const) : undefined,
    query: { enabled: allowanceEnabled, refetchInterval: 15_000 },
  });

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
  ]);

  useEffect(() => {
    if (!quote) return;
    const expires = new Date(quote.expires_at).getTime();
    const delay = expires - Date.now() - 1_000;
    const timer = setTimeout(() => {
      setQuote(null);
      setRefreshNonce((prev) => prev + 1);
    }, Math.max(delay, 0));
    return () => clearTimeout(timer);
  }, [quote]);

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
  const requiredAllowance = useMemo(() => {
    if (!quote?.stake_wei) return 0n;
    try {
      return BigInt(quote.stake_wei);
    } catch {
      return 0n;
    }
  }, [quote?.stake_wei]);
  const hasAllowance = allowance !== undefined && allowance !== null && allowance >= requiredAllowance;
  const needsApproval = allowanceEnabled && requiredAllowance > 0n && !hasAllowance;
  const currentPrice = priceForOutcome(selectedOutcome);
  const stakeDisplay = Number.isFinite(stakeZen) && stakeZen > 0 ? `${stakeZen.toFixed(2)} ZEN` : null;
  const ctaLabel = loading
    ? "Pricing…"
    : `Buy ${outcomeLabel}${stakeDisplay ? ` with ${stakeDisplay}` : ""}`;

  const highlightClass =
    selectedOutcome === 0
      ? "shadow-[0_20px_60px_rgba(16,185,129,0.25)] ring-1 ring-emerald-400/30"
      : "shadow-[0_20px_60px_rgba(244,63,94,0.25)] ring-1 ring-rose-400/30";

  const handleTrade = async () => {
    setTxError(null);
    setTxHash(null);
    if (tradingDisabled) {
      setTxError(tradingReason ?? "Trading disabled");
      return;
    }
    if (!address) {
      setError("Connect wallet to request a quote");
      setTxError("Connect wallet before trading.");
      return;
    }
    if (!marketAddress) {
      setTxError("Market contract address missing.");
      return;
    }
    if (!quote) {
      setError("Requesting quote before trading…");
      setRefreshNonce((prev) => prev + 1);
      return;
    }
    if (stakeZen < MIN_STAKE_ZEN || stakeZen > MAX_STAKE_ZEN) {
      setTxError(STAKE_RANGE_ERROR);
      return;
    }
    if (stakeZen !== quote.stake_zen) {
      setTxError("Stake changed. Refresh the quote.");
      return;
    }
    const expiresTs = new Date(quote.expires_at).getTime();
    if (expiresTs <= Date.now()) {
      setTxError("Quote expired. Refreshing…");
      setRefreshNonce((prev) => prev + 1);
      return;
    }
    if (quote.chain_id && chainId && Number(quote.chain_id) !== chainId) {
      setTxError(`Switch to chain ${quote.chain_id} to trade.`);
      return;
    }
    if (missingZenToken) {
      setTxError("ZEN token address is not configured.");
      return;
    }
    setTxLoading(true);
    try {
      if (needsApproval) {
        const hash = await writeApprovalAsync({
          address: ZEN_TOKEN_ADDRESS as Address,
          abi: erc20Abi,
          functionName: "approve",
          args: [marketAddress as Address, maxUint256],
          chainId,
        });
        setApprovalHash(hash as Hex);
        if (publicClient) {
          await publicClient.waitForTransactionReceipt({ hash: hash as Hex });
          await refetchAllowance();
        }
      }
      const params = buildSignedQuoteParams({
        quote,
        outcomeId: selectedOutcome,
        walletAddress: address as Address,
        amountWei: BigInt(quote.stake_wei),
      });
      const tx = await commitWithQuote(params);
      setTxHash(typeof tx === "string" ? tx : (tx as any)?.hash ?? null);
    } catch (err) {
      setTxError(err instanceof Error ? err.message : "Trade failed");
    } finally {
      setTxLoading(false);
    }
  };

  return (
    <div
      className={`md:sticky md:top-0 self-start rounded-3xl border border-white/10 bg-slate-950/80 p-5 text-sm text-slate-100 backdrop-blur ${highlightClass}`}
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
              Quote {quote.quote_id.slice(0, 6)}… expires {formatTime(quote.expires_at)}
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
              if (capped < MIN_STAKE_ZEN || capped > MAX_STAKE_ZEN) {
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
              if (capped < MIN_STAKE_ZEN || capped > MAX_STAKE_ZEN) {
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
            {[MIN_STAKE_ZEN, 1, MAX_STAKE_ZEN].map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => {
                  const capped = Math.min(preset, effectiveMaxStake);
                  setStakeZen(capped);
                  setStakeInput(capped.toFixed(2));
                  if (capped < MIN_STAKE_ZEN || capped > MAX_STAKE_ZEN) {
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
            !marketAddress ||
            !address ||
            stakeZen < MIN_STAKE_ZEN ||
            stakeZen > MAX_STAKE_ZEN ||
            tradingDisabled ||
            txLoading ||
            txPending
          }
          onClick={handleTrade}
          className={`inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] transition ${
            loading || fxStale || fxUnavailable || !address || !marketAddress || tradingDisabled || txLoading || txPending
              ? "cursor-not-allowed bg-white/20 text-white/60"
              : "bg-emerald-500 text-white hover:bg-emerald-400"
          }`}
        >
          {tradingReason ??
            (txLoading || txPending ? "Submitting…" : ctaLabel)}
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
        {quote && needsApproval && !txLoading && !txPending && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-amber-200">
            Wallet will request ZEN approval before trading.
          </p>
        )}
        {missingZenToken && (
          <p className="text-xs text-rose-200">
            ZEN token address missing. Set NEXT_PUBLIC_ZEN_TOKEN_ADDRESS to continue.
          </p>
        )}
        {(approvalHash || txHash) && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-200">
            {approvalHash ? `Approval tx: ${approvalHash.slice(0, 10)}…${approvalHash.slice(-6)}` : null}
            {approvalHash && txHash ? " · " : ""}
            {txHash ? `Commit tx: ${txHash.slice(0, 10)}…${txHash.slice(-6)}` : null}
          </p>
        )}
        {commitError && !txError && (
          <p className="text-xs text-rose-300">
            {commitError instanceof Error ? commitError.message : "Commit failed. Check wallet and quote."}
          </p>
        )}
        {approvalError && !txError && (
          <p className="text-xs text-rose-300">
            {approvalError instanceof Error ? approvalError.message : "Approval failed. Try again."}
          </p>
        )}
        {allowanceLoading && <p className="text-xs text-slate-400">Checking ZEN allowance…</p>}
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
