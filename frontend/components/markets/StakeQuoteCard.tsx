"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchPricingQuoteWithMeta,
  FX_DEFAULT_PATH,
  type PricingQuote,
  fetchPricingPreview,
  submitTrade,
  type TradeCommitResponse,
} from "@/lib/pricing-client";
import { fetchPositions, fetchTradeStatus } from "@/lib/api";
import { useFxStream } from "@/hooks/useFxStream";
import { useChainId, useConnection, useSignMessage } from "wagmi";
import { formatTime, normalizeTxHash } from "@/lib/formatters";
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

const TICKET_SIZE_ZEN = 0.1;
const PER_BET_CAP_ZEN = TICKET_SIZE_ZEN;
const MIN_STAKE_ZEN = TICKET_SIZE_ZEN;
const STAKE_RANGE_ERROR = `Stake must be exactly ${TICKET_SIZE_ZEN} ZEN (fixed ticket size)`;
const QUOTE_REFRESH_INTERVAL_MS = 10_000;
const PREVIEW_MIN_INTERVAL_MS = QUOTE_REFRESH_INTERVAL_MS;
const PREVIEW_RETRY_INTERVAL_MS = 1_000;

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

const buildPreviewKey = (
  address: string | undefined,
  marketId: string | undefined,
  outcomeId: number | undefined,
  stakeZen: number,
  chainId: number | undefined,
): string | null => {
  if (!address || !marketId || outcomeId === undefined || outcomeId === null || !Number.isFinite(stakeZen)) return null;
  return `${address.toLowerCase()}|${marketId}|${outcomeId}|${stakeZen.toFixed(4)}|${chainId ?? "chain"}`;
};

const shortenHash = (hash?: string | null): string | null => {
  if (!hash) return null;
  const trimmed = hash.trim();
  if (!trimmed) return null;
  if (trimmed.length <= 16) return trimmed;
  return `${trimmed.slice(0, 10)}...${trimmed.slice(-6)}`;
};

export function StakeQuoteCard({
  defaultStakeZen = TICKET_SIZE_ZEN,
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
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const previewKeyRef = useRef<string | null>(null);
  const previewInFlightRef = useRef(false);
  const lastPreviewAtRef = useRef(0);
  const [escrowBalanceZen, setEscrowBalanceZen] = useState<number | null>(null);
  const { fx, status } = useFxStream(FX_DEFAULT_PATH);
  const fxIsStale = Boolean(fx?.stale);
  const fxStale = status === "stale";
  const { address } = useConnection();
  const { mutateAsync: signMessage } = useSignMessage();
  const chainId = useChainId();
  const expectedChainId = defaultChain.id;
  const chainMismatch = Boolean(chainId && chainId !== expectedChainId);
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(initialTxHash);
  const [relayerJobId, setRelayerJobId] = useState<string | null>(null);
  const [txConfirmed, setTxConfirmed] = useState(false);
  const [txStatus, setTxStatus] = useState<string | null>(null);
  const explorerBaseRaw =
    process.env.NEXT_PUBLIC_EXPLORER_BASE_URL ||
    (defaultChain.blockExplorers?.default?.url ? defaultChain.blockExplorers.default.url : "");
  const explorerBase = explorerBaseRaw ? explorerBaseRaw.replace(/\/+$/, "") : "";
  const txPending = false;
  const [quoteCountdown, setQuoteCountdown] = useState<string | null>(null);
  const [quoteRefreshing, setQuoteRefreshing] = useState(false);
  const lastMarketRef = useRef<string | null>(null);
  const fxUnavailable = status === "error";
  const outcomeOptions = useMemo(() => (outcomes.length ? outcomes : ["Yes", "No"]), [outcomes]);
  const isBinary = outcomeOptions.length === 2;
  const normalizedPrices = useMemo(() => (Array.isArray(outcomePrices) ? outcomePrices : []), [outcomePrices]);
  const priceForOutcome = useCallback(
    (index: number): number | null => {
      const value = normalizedPrices[index];
      if (Number.isFinite(value)) return value;
      return null;
    },
    [normalizedPrices],
  );
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
  const quoteExpiryMs = useMemo(() => getQuoteExpiryMs(quote), [quote]);
  const quoteExpired = quoteExpiryMs ? quoteExpiryMs <= Date.now() : false;

  useEffect(() => {
    if (selectedOutcome >= outcomeOptions.length) {
      setSelectedOutcome(0);
    }
  }, [outcomeOptions, selectedOutcome]);

  useEffect(() => {
    let cancelled = false;
    setEscrowBalanceZen(null);
    if (!address) return undefined;
    const loadEscrow = async () => {
      try {
        const resp = await fetchPositions(address);
        if (cancelled) return;
        const escrowRaw = resp.escrowBalance ?? null;
        if (escrowRaw === null || escrowRaw === undefined) {
          setEscrowBalanceZen(null);
          return;
        }
        const escrowNumber = typeof escrowRaw === "string" ? Number(escrowRaw) : Number(escrowRaw);
        const escrowZen = Number.isFinite(escrowNumber) ? escrowNumber / 1e18 : null;
        setEscrowBalanceZen(escrowZen);
      } catch {
        if (!cancelled) {
          setEscrowBalanceZen(null);
        }
      }
    };
    loadEscrow();
    return () => {
      cancelled = true;
    };
  }, [address]);

  const statusNormalized = (marketStatus ?? "").toLowerCase();
  const settledStates = ["settled", "resolved", "closed", "cancelled", "canceled", "voided"];
  const lockedStates = ["locked", "disputed"];
  const isSettled = isResolved === true || settledStates.includes(statusNormalized);
  const isLocked = lockedStates.includes(statusNormalized);
  const normalizedMarketAddress =
    typeof marketAddress === "string" && marketAddress.trim().length > 0 ? marketAddress.trim() : undefined;
  const missingMarketAddress = !normalizedMarketAddress;
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
    // Switching outcomes should invalidate any issued quote.
    setQuote(null);
    setRefreshNonce((prev) => prev + 1);
  }, [selectedOutcome]);

  useEffect(() => {
    // If the user adjusts stake, ensure we request a fresh preview right away.
    if (!quote) return;
    const stakeChanged =
      !Number.isFinite(debouncedStake) || Math.abs(Number(quote.stake_zen ?? NaN) - debouncedStake) > 1e-6;
    if (stakeChanged) {
      setQuote(null);
      setQuoteRefreshing(true);
      setRefreshNonce((prev) => prev + 1);
      previewKeyRef.current = null;
      lastPreviewAtRef.current = 0;
    }
  }, [debouncedStake, quote]);

  useEffect(() => {
    // Reset quotes immediately when changing markets or stake to avoid stale previews carrying over.
    const marketKey = `${marketId ?? "market"}|${normalizedMarketAddress ?? "address"}`;
    if (lastMarketRef.current !== marketKey) {
      lastMarketRef.current = marketKey;
      setQuote(null);
      setQuoteRefreshing(true);
      setRefreshNonce((prev) => prev + 1);
      previewKeyRef.current = null;
      lastPreviewAtRef.current = 0;
      setStakeZen(defaultStakeZen);
      setStakeInput(defaultStakeZen.toFixed(2));
      setSelectedOutcome(initialOutcomeId);
      setError(null);
    }
  }, [marketId, normalizedMarketAddress, defaultStakeZen, initialOutcomeId]);

  useEffect(() => {
    // Force an immediate preview refresh when the user changes key inputs.
    previewKeyRef.current = null;
    lastPreviewAtRef.current = 0;
  }, [debouncedStake, selectedOutcome, address, chainId]);

  useEffect(() => {
    let cancelled = false;
    const requestPreview = async () => {
      // Keep an issued quote intact; only refresh previews while unsigned.
      const quoteMatchesSelection =
        quote &&
        !quoteExpired &&
        (quote.market_id ?? marketId) === marketId &&
        (quote.outcome_id ?? selectedOutcome) === selectedOutcome &&
        Math.abs(Number(quote.stake_zen ?? NaN) - debouncedStake) < 1e-6;
      if (quoteMatchesSelection) {
        setQuoteRefreshing(false);
        return;
      }
      if (tradingDisabled) {
        setQuoteRefreshing(false);
        setQuote(null);
        setError(tradingReason ?? "Trading disabled");
        return;
      }
      if (!address) {
        setQuoteRefreshing(false);
        setQuote(null);
        setError("Connect wallet to request a quote");
        return;
      }
      if (!marketId) {
        setQuoteRefreshing(false);
        setQuote(null);
        setError("Market unavailable (missing id)");
        return;
      }
      if (!chainId || chainMismatch) {
        setQuoteRefreshing(false);
        setQuote(null);
        setError(`Switch to ${defaultChain.name} to trade`);
        return;
      }
      if (debouncedStake < MIN_STAKE_ZEN) {
        setQuoteRefreshing(false);
        setQuote(null);
        setError(STAKE_RANGE_ERROR);
        setStakeZen(TICKET_SIZE_ZEN);
        setStakeInput(TICKET_SIZE_ZEN.toFixed(2));
        return;
      }
      if (capExhausted) {
        setQuoteRefreshing(false);
        setQuote(null);
        setError("Stake cap exhausted for this market/user");
        return;
      }
      if (fxUnavailable) {
        setQuoteRefreshing(false);
        setQuote(null);
        setError("FX feed unavailable");
        return;
      }
      if (!Number.isFinite(debouncedStake) || debouncedStake <= 0) {
        setError(STAKE_RANGE_ERROR);
        return;
      }
      if (fxIsStale) {
        setError("Pricing paused (FX stale)");
        return;
      }
      const cappedStake = Math.min(TICKET_SIZE_ZEN, effectiveMaxStake);
      if (cappedStake !== TICKET_SIZE_ZEN) {
        setStakeZen(cappedStake);
        setStakeInput(cappedStake.toFixed(2));
        setError(`Stake capped at ${cappedStake.toFixed(3)} ZEN`);
      } else if (debouncedStake !== TICKET_SIZE_ZEN) {
        setStakeZen(TICKET_SIZE_ZEN);
        setStakeInput(TICKET_SIZE_ZEN.toFixed(2));
      }
      const previewKey = buildPreviewKey(address, marketId, selectedOutcome, cappedStake, chainId);
      if (previewKey && previewKeyRef.current === previewKey && quote) {
        if (!quoteRefreshing && !quoteExpired) return;
      }
      if (previewInFlightRef.current) return;
      const now = Date.now();
      const minInterval = quote && !quoteExpired ? PREVIEW_MIN_INTERVAL_MS : PREVIEW_RETRY_INTERVAL_MS;
      if (now - lastPreviewAtRef.current < minInterval) return;
      lastPreviewAtRef.current = now;
      previewInFlightRef.current = true;
      previewKeyRef.current = previewKey;
      const shouldBlockCta = !quote || quoteExpired || quoteRefreshing;
      if (shouldBlockCta) {
        setQuoteRefreshing(true);
      }
      try {
        const payload = await fetchPricingPreview(cappedStake, {
          marketId,
          walletAddress: address,
          marketAddress: normalizedMarketAddress,
          outcomeId: selectedOutcome,
        });
        if (!cancelled) {
          setQuote(payload);
          setError(null);
          setQuoteRefreshing(false);
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "Quote failed";
        if (!cancelled) {
          if (typeof console !== "undefined") {
            console.error("[quote] request failed", err);
          }
          setError(message);
          setQuoteRefreshing(false);
        }
      } finally {
        previewInFlightRef.current = false;
        // no-op: CTA stays active while preview refreshes
      }
    };
    requestPreview();
    return () => {
      cancelled = true;
    };
  }, [
    address,
    capExhausted,
    chainId,
    chainMismatch,
    debouncedStake,
    effectiveMaxStake,
    fxIsStale,
    fxUnavailable,
    normalizedMarketAddress,
    marketId,
    quote,
    quoteExpired,
    quoteRefreshing,
    refreshNonce,
    selectedOutcome,
    tradingDisabled,
    tradingReason,
  ]);

  useEffect(() => {
    previewKeyRef.current = null;
  }, [refreshNonce]);

  useEffect(() => {
    if (!address || !marketId || tradingDisabled || fxUnavailable || chainMismatch) return;
    if (quote && !quoteExpired && !quoteRefreshing) return;
    const intervalMs = quote && !quoteExpired ? QUOTE_REFRESH_INTERVAL_MS : PREVIEW_RETRY_INTERVAL_MS;
    const timer = setInterval(() => {
      setRefreshNonce((prev) => prev + 1);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [address, marketId, tradingDisabled, fxUnavailable, chainMismatch, quote, quoteExpired, quoteRefreshing]);

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
        setQuoteRefreshing(true);
        previewKeyRef.current = null;
        lastPreviewAtRef.current = 0;
        setRefreshNonce((prev) => prev + 1);
        return false;
      }
      const seconds = Math.ceil(remainingMs / 1000);
      const displaySeconds = Math.max(0, seconds);
      setQuoteCountdown(`${displaySeconds}s`);
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
    setQuoteRefreshing(false);
    setError(null);
    setRefreshNonce((prev) => prev + 1);
    if (!initialTxHash) {
      setTxHash(null);
    }
    setRelayerJobId(null);
    setTxConfirmed(false);
    setTxStatus(null);
  }, [chainId, address, initialTxHash]);

  const toWinZen = useMemo(() => {
    const outcomePrice = priceForOutcome(selectedOutcome);
    if (Number.isFinite(stakeZen) && outcomePrice && outcomePrice > 0) {
      // Derive payout from quoted probability to reflect selected outcome.
      return stakeZen / outcomePrice;
    }
    if (!quote) return null;
    if (quote.payout_zen !== null && quote.payout_zen !== undefined && Number.isFinite(Number(quote.payout_zen))) {
      return Number(quote.payout_zen);
    }
    if (Number.isFinite(quote.stake_zen)) {
      return Number(quote.stake_zen);
    }
    return null;
  }, [quote, priceForOutcome, selectedOutcome, stakeZen]);
  const stakeDisplay = Number.isFinite(stakeZen) && stakeZen > 0 ? `${stakeZen.toFixed(2)} ZEN` : null;
  const normalizedTxHash = normalizeTxHash(txHash);
  const txHashIsHex = Boolean(normalizedTxHash);
  const txHashDisplay = normalizedTxHash ?? (typeof txHash === "string" ? txHash.trim() : "");
  const ctaLabel = txLoading
    ? "Submitting..."
    : `Buy ${outcomeLabel}${stakeDisplay ? ` with ${stakeDisplay}` : ""}`;
  const txStatusLabel =
    txLoading
      ? "Committing..."
      : txStatus === "failed"
        ? "Commit failed"
        : txConfirmed || txStatus === "confirmed"
          ? "Committed"
          : txStatus === "pending" || relayerJobId
            ? "Confirming..."
            : null;
  const shortQuoteId = shortenHash(quote?.quote_id ?? null);

  const highlightClass =
    selectedOutcome === 0
      ? "shadow-[0_20px_60px_rgba(16,185,129,0.25)] ring-1 ring-emerald-400/30"
      : "shadow-[0_20px_60px_rgba(244,63,94,0.25)] ring-1 ring-rose-400/30";
  const stakeOutOfRange =
    !Number.isFinite(stakeZen) || stakeZen < MIN_STAKE_ZEN || stakeZen > effectiveMaxStake || capExhausted;
  const escrowInsufficient = useMemo(() => {
    const balanceKnown = Number.isFinite(escrowBalanceZen);
    const insufficientBalance = balanceKnown ? Number(escrowBalanceZen) < stakeZen : false;
    const normalizedError = txError?.toLowerCase() ?? "";
    const errorIndicatesInsufficient =
      normalizedError.includes("insufficient_escrow_balance") || normalizedError.includes("insufficient escrow balance");
    return insufficientBalance || errorIndicatesInsufficient;
  }, [escrowBalanceZen, stakeZen, txError]);
  const submitBlockedReason =
    (escrowInsufficient ? "Deposit to escrow" : null) ??
    tradingReason ??
    (!address ? "Connect wallet" : null) ??
    (!marketId ? "Market unavailable" : null) ??
    (chainMismatch ? `Switch to ${defaultChain.name}` : null) ??
    (capExhausted ? "Stake cap reached" : null) ??
    (stakeOutOfRange ? STAKE_RANGE_ERROR : null) ??
    (fxUnavailable ? "FX unavailable" : null) ??
    (fxStale ? "FX stale" : null) ??
    null;

  const handleTrade = async () => {
    setTxError(null);
    setTxHash(null);
    setRelayerJobId(null);
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
    if (capExhausted) {
      setTxError("Stake cap reached for this market/user.");
      return;
    }
    if (stakeOutOfRange) {
      setTxError(STAKE_RANGE_ERROR);
      return;
    }
    if (!chainId || chainMismatch) {
      setTxError(`Switch to ${defaultChain.name} to trade.`);
      return;
    }
    if (fxStale || fxUnavailable) {
      setTxError("FX is stale or unavailable; retry once fresh.");
      return;
    }
    setTxLoading(true);
    try {
      const previewQuote = quote && !quoteExpired ? quote : null;
      const needsFreshQuote =
        !previewQuote ||
        !previewQuote.quote_id ||
        (previewQuote.market_id ?? marketId) !== marketId ||
        (previewQuote.outcome_id ?? selectedOutcome) !== selectedOutcome ||
        Math.abs(Number(previewQuote.stake_zen ?? NaN) - stakeZen) > 1e-6;
      const issuedQuote = needsFreshQuote
        ? await fetchPricingQuoteWithMeta(stakeZen, {
            marketId,
            walletAddress: address,
            marketAddress: normalizedMarketAddress,
            outcomeId: selectedOutcome,
          })
        : previewQuote;
      setQuote(issuedQuote);
      if (!issuedQuote.quote_id) {
        setTxError("Quote unavailable");
        return;
      }
      const issuedExpiry = getQuoteExpiryMs(issuedQuote);
      if (!issuedExpiry || issuedExpiry <= Date.now()) {
        setTxError("Quote expired. Refreshing...");
        setRefreshNonce((prev) => prev + 1);
        return;
      }
      if (issuedQuote.chain_id && chainId && Number(issuedQuote.chain_id) !== chainId) {
        setTxError(`Switch to chain ${issuedQuote.chain_id} to trade.`);
        return;
      }
      if (stakeZen !== issuedQuote.stake_zen) {
        setTxError("Stake changed. Refresh the quote.");
        return;
      }
      const signature = await signMessage({
        message: `commit:${issuedQuote.quote_id}:${address.toLowerCase()}`,
      });
      const resp: TradeCommitResponse = await submitTrade(issuedQuote.quote_id, address, signature);
      const respJob = resp.relayer_job_id ? String(resp.relayer_job_id) : null;
      const respHash = resp.tx_hash || null;
      if (respHash || respJob) {
        const normalizedHash = normalizeTxHash(respHash) ?? respHash;
        setTxHash(normalizedHash || null);
        setRelayerJobId(respJob);
        const initialStatus = resp.relayer_status || (respHash ? "pending" : null);
        setTxStatus(initialStatus);
        setTxConfirmed(initialStatus === "confirmed");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Trade failed";
      const normalized = message.toLowerCase();
      if (normalized.includes("expired")) {
        setTxError("Quote expired. Refreshing...");
        setRefreshNonce((prev) => prev + 1);
      } else if (normalized.includes("consume") || normalized.includes("used") || normalized.includes("replay")) {
        setTxError("Quote already consumed. Requesting a new one.");
        setRefreshNonce((prev) => prev + 1);
      } else if (normalized.includes("insufficient_escrow_balance")) {
        setTxError("Insufficient escrow balance. Deposit more in the dashboard.");
      } else {
        if (typeof console !== "undefined") {
          console.error("[trade] submit failed", err);
        }
        setTxError(message);
      }
    } finally {
      setTxLoading(false);
    }
  };

  // Poll transaction status if we have a hash/job id.
  useEffect(() => {
    if (!txHash && !relayerJobId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const isHexHash = normalizeTxHash(txHash);
        const statusResp = await fetchTradeStatus(
          isHexHash ?? undefined,
          relayerJobId || (!isHexHash && txHash ? txHash : undefined),
        );
        if (!cancelled) {
          setTxStatus(statusResp.status);
          const nextHash = normalizeTxHash(statusResp.txHash) ?? statusResp.txHash;
          if (nextHash && nextHash !== txHash) {
            setTxHash(nextHash);
          }
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
  }, [txHash, relayerJobId]);

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
            name="stakeZen"
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
              const normalizedInput = raw.replace(",", ".");
              const pattern = /^\d*(?:\.\d{0,2})?$/;
              if (normalizedInput !== "" && !pattern.test(normalizedInput)) {
                return;
              }
              setStakeInput(raw);
              if (normalizedInput === "") {
                setStakeZen(0);
                setStakeError(STAKE_RANGE_ERROR);
                return;
              }
              const next = Number(normalizedInput);
              if (Number.isNaN(next)) {
                setStakeZen(0);
                setStakeError(STAKE_RANGE_ERROR);
                return;
              }
              const rounded = Math.round(next * 100) / 100;
              const capped = Math.min(Math.max(rounded, 0), effectiveMaxStake);
              const snapped = capped > 0 ? TICKET_SIZE_ZEN : 0;
              setStakeZen(snapped);
              setStakeInput(snapped.toFixed(2));
              if (snapped !== TICKET_SIZE_ZEN || snapped > effectiveMaxStake) {
                setStakeError(STAKE_RANGE_ERROR);
              } else {
                setStakeError(null);
              }
            }}
            onBlur={() => {
              const normalizedInput = stakeInput.replace(",", ".");
              const next = Number(normalizedInput);
              if (Number.isNaN(next)) {
                setStakeInput("0.00");
                setStakeZen(0);
                setStakeError(STAKE_RANGE_ERROR);
                return;
              }
              const rounded = Math.round(next * 100) / 100;
              const capped = Math.min(Math.max(rounded, 0), effectiveMaxStake);
              const snapped = capped > 0 ? TICKET_SIZE_ZEN : 0;
              setStakeZen(snapped);
              setStakeInput(snapped.toFixed(2));
              if (snapped !== TICKET_SIZE_ZEN || snapped > effectiveMaxStake) {
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
            {[TICKET_SIZE_ZEN, TICKET_SIZE_ZEN, TICKET_SIZE_ZEN].map((preset, idx) => (
              <button
                key={`${preset}-${idx}`}
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
          <Metric label="To win" value={`${formatNumber(toWinZen ?? NaN, 3)} ZEN`} highlight />
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-2">
        {tradingDisabled && tradingReason !== "Market settled" && (
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
            fxStale ||
            fxUnavailable ||
            !marketId ||
            !address ||
            stakeOutOfRange ||
            tradingDisabled ||
            capExhausted ||
            chainMismatch ||
            escrowInsufficient ||
            txLoading ||
            txPending
          }
          onClick={handleTrade}
          className={`inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] transition ${
            fxStale ||
            fxUnavailable ||
            !address ||
            tradingDisabled ||
            capExhausted ||
            chainMismatch ||
            escrowInsufficient ||
            txLoading ||
            txPending
              ? "cursor-not-allowed bg-white/20 text-white/60"
              : "bg-emerald-500 text-white hover:bg-emerald-400"
          }`}
        >
          {submitBlockedReason ?? ctaLabel}
        </button>
        {shortQuoteId && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
            Quote id: <span className="font-semibold text-white">{shortQuoteId}</span>
          </p>
        )}
        {quote && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
            Quote {shortQuoteId ?? "preview"} expires in{" "}
            {quoteCountdown ?? formatTime(quote.expires_at ?? quoteExpiryMs ?? undefined)}
          </p>
        )}
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
        {error && error !== "Market settled" && <p className="text-xs text-rose-300">{error}</p>}
        {txError && <p className="text-xs text-rose-300">{txError}</p>}
        {escrowInsufficient && (
          <p className="text-xs text-emerald-200">
            Deposit to escrow in the{" "}
            <Link className="underline hover:text-emerald-100" href="/dashboard">
              dashboard
            </Link>{" "}
            to continue trading.
          </p>
        )}
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
        {txStatusLabel && (
          <p
            className={`text-[11px] uppercase tracking-[0.2em] ${
              txStatus === "failed" ? "text-rose-200" : "text-emerald-200"
            }`}
          >
            {txStatusLabel}{" "}
            {relayerJobId && !txHashIsHex ? `(job ${relayerJobId})` : null}
          </p>
        )}
        {relayerJobId && !txHashIsHex && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-300">
            Waiting for the relayer to return the commit transaction hash...
          </p>
        )}
        {txHashIsHex && txHash && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-200">
            Commit tx:{" "}
            {explorerBase ? (
              <a
                href={`${explorerBase}/tx/${normalizedTxHash}`}
                target="_blank"
                rel="noreferrer"
                className="underline decoration-dotted"
              >
                {txHashDisplay.slice(0, 10)}...{txHashDisplay.slice(-6)}
              </a>
            ) : (
              `${txHashDisplay.slice(0, 10)}...${txHashDisplay.slice(-6)}`
            )}{" "}
            ({txStatus ?? "pending"})
          </p>
        )}
        {txConfirmed && txHashIsHex && txHash && (
          <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-200">
            Commit confirmed on-chain.
          </p>
        )}
      </div>
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
