"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchPricingQuoteWithMeta,
  fetchPricingPreview,
  FX_DEFAULT_PATH,
  type PricingQuote,
  submitTrade,
  type TradeCommitResponse,
} from "@/lib/pricing-client";
import { fetchPositions, fetchTradeStatus } from "@/lib/api";
import { useFxStream } from "@/hooks/useFxStream";
import { useChainId, useConnection, useSignMessage } from "wagmi";
import { normalizeTxHash } from "@/lib/formatters";
import { buildCommitSignatureMessage } from "@/lib/signature-messages";
import { defaultChain } from "@/lib/wagmi";
import { StakeInput } from "./StakeInput";
import { QuoteDisplay } from "./QuoteDisplay";
import { TradeSubmission } from "./TradeSubmission";

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
  onOutcomeChangeAction?: (outcomeId: number) => void;
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
  onOutcomeChangeAction,
}: Props) {
  // ── Stake & outcome state ──────────────────────────────────────────────
  const [stakeZen, setStakeZen] = useState<number>(defaultStakeZen);
  const [, setStakeInput] = useState<string>(defaultStakeZen.toFixed(2));
  const [stakeError] = useState<string | null>(null);
  const [selectedOutcome, setSelectedOutcome] = useState<number>(initialOutcomeId);

  // ── Quote state ────────────────────────────────────────────────────────
  const [quote, setQuote] = useState<PricingQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const previewKeyRef = useRef<string | null>(null);
  const previewInFlightRef = useRef(false);
  const lastPreviewAtRef = useRef(0);
  const [quoteCountdown, setQuoteCountdown] = useState<string | null>(null);
  const [quoteRefreshing, setQuoteRefreshing] = useState(false);
  const lastMarketRef = useRef<string | null>(null);

  // ── Transaction state ──────────────────────────────────────────────────
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);
  const [txHash, setTxHash] = useState<string | null>(initialTxHash);
  const [relayerJobId, setRelayerJobId] = useState<string | null>(null);
  const [relayerPendingSince, setRelayerPendingSince] = useState<number | null>(null);
  const [txConfirmed, setTxConfirmed] = useState(false);
  const [txStatus, setTxStatus] = useState<string | null>(null);

  // ── Wallet & chain context ─────────────────────────────────────────────
  const [escrowBalanceZen, setEscrowBalanceZen] = useState<number | null>(null);
  const { fx, status } = useFxStream(FX_DEFAULT_PATH);
  const fxIsStale = Boolean(fx?.stale);
  const fxStale = status === "stale";
  const { address } = useConnection();
  const { mutateAsync: signMessage } = useSignMessage();
  const chainId = useChainId();
  const expectedChainId = defaultChain.id;
  const chainMismatch = Boolean(chainId && chainId !== expectedChainId);
  const explorerBaseRaw =
    process.env.NEXT_PUBLIC_EXPLORER_BASE_URL ||
    (defaultChain.blockExplorers?.default?.url ? defaultChain.blockExplorers.default.url : "");
  const explorerBase = explorerBaseRaw ? explorerBaseRaw.replace(/\/+$/, "") : "";
  const txPending = false;
  const fxUnavailable = status === "error";

  // ── Derived values ─────────────────────────────────────────────────────
  const outcomeOptions = useMemo(() => (outcomes.length ? outcomes : ["Yes", "No"]), [outcomes]);
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

  // ── Market status ──────────────────────────────────────────────────────
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

  // ── CTA derivations ────────────────────────────────────────────────────
  const toWinZen = useMemo(() => {
    if (quote?.payout_zen !== null && quote?.payout_zen !== undefined && Number.isFinite(Number(quote.payout_zen))) {
      return Number(quote.payout_zen);
    }
    return null;
  }, [quote]);

  const stakeDisplay = Number.isFinite(stakeZen) && stakeZen > 0 ? `${stakeZen.toFixed(2)} ZEN` : null;
  const ctaLabel = txLoading
    ? "Submitting..."
    : `Buy ${outcomeLabel}${stakeDisplay ? ` with ${stakeDisplay}` : ""}`;
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
    (!quote ? "Waiting for quote..." : null) ??
    (quoteExpired ? "Quote expired. Refreshing..." : null) ??
    (capExhausted ? "Stake cap reached" : null) ??
    (stakeOutOfRange ? STAKE_RANGE_ERROR : null) ??
    (fxUnavailable ? "FX unavailable" : null) ??
    (fxStale ? "FX stale" : null) ??
    null;

  const ctaDisabled =
    fxStale ||
    fxUnavailable ||
    !marketId ||
    !address ||
    !quote ||
    quoteExpired ||
    quoteRefreshing ||
    stakeOutOfRange ||
    tradingDisabled ||
    capExhausted ||
    chainMismatch ||
    escrowInsufficient ||
    txLoading ||
    txPending;

  const sanitizeTradeErrorMessage = useCallback((err: unknown): string => {
    const raw = err instanceof Error ? err.message : String(err);
    const [withoutVersion] = raw.split("Version:");
    const cleaned = withoutVersion.replace(/^Details:\s*/i, "").trim();
    const normalized = cleaned.toLowerCase();
    if (
      normalized.includes("user rejected") ||
      normalized.includes("rejected the request") ||
      normalized.includes("user denied")
    ) {
      return "User rejected the request.";
    }
    return cleaned || "Trade failed";
  }, []);

  // ── Effects: outcome bounds ────────────────────────────────────────────
  useEffect(() => {
    if (selectedOutcome >= outcomeOptions.length) {
      setSelectedOutcome(0);
    }
  }, [outcomeOptions, selectedOutcome]);

  useEffect(() => {
    if (typeof onOutcomeChangeAction === "function") {
      onOutcomeChangeAction(selectedOutcome);
    }
  }, [selectedOutcome, onOutcomeChangeAction]);

  // ── Effects: escrow balance ────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setEscrowBalanceZen(null);
    if (!address) return undefined;
    const loadEscrow = async () => {
      try {
        // Do not prompt for signatures on page load; signing is reserved for explicit buy actions.
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
    void loadEscrow();
    return () => {
      cancelled = true;
    };
  }, [address]);

  // ── Effects: quote lifecycle ───────────────────────────────────────────
  useEffect(() => {
    setQuote(null);
    setRefreshNonce((prev) => prev + 1);
  }, [selectedOutcome]);

  useEffect(() => {
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
    previewKeyRef.current = null;
    lastPreviewAtRef.current = 0;
  }, [debouncedStake, selectedOutcome, address, chainId]);

  // ── Effect: preview fetcher ────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    const requestPreview = async () => {
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
        setError(`Stake capped at ${cappedStake.toFixed(4)} ZEN`);
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
          setError(message);
          setQuoteRefreshing(false);
        }
      } finally {
        previewInFlightRef.current = false;
      }
    };
    void requestPreview();
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

  // ── Effect: auto-refresh timer ─────────────────────────────────────────
  useEffect(() => {
    if (!address || !marketId || tradingDisabled || fxUnavailable || chainMismatch) return;
    if (quote && !quoteExpired && !quoteRefreshing) return;
    const intervalMs = quote && !quoteExpired ? QUOTE_REFRESH_INTERVAL_MS : PREVIEW_RETRY_INTERVAL_MS;
    const timer = setInterval(() => {
      setRefreshNonce((prev) => prev + 1);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [address, marketId, tradingDisabled, fxUnavailable, chainMismatch, quote, quoteExpired, quoteRefreshing]);

  // ── Effect: countdown ──────────────────────────────────────────────────
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

  // ── Effect: chain/account reset ────────────────────────────────────────
  useEffect(() => {
    setQuote(null);
    setQuoteRefreshing(false);
    setError(null);
    setRefreshNonce((prev) => prev + 1);
    if (!initialTxHash) {
      setTxHash(null);
    }
    setRelayerJobId(null);
    setRelayerPendingSince(null);
    setTxConfirmed(false);
    setTxStatus(null);
  }, [chainId, address, initialTxHash]);

  // ── Trade handler ──────────────────────────────────────────────────────
  const handleTrade = useCallback(async () => {
    setTxError(null);
    setTxHash(null);
    setRelayerJobId(null);
    setRelayerPendingSince(null);
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
      // Always fetch a fresh full quote for commit — previews lack quote_id
      const issuedQuote = await fetchPricingQuoteWithMeta(stakeZen, {
        marketId,
        walletAddress: address,
        marketAddress: normalizedMarketAddress,
        outcomeId: selectedOutcome,
      });
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
        message: buildCommitSignatureMessage(issuedQuote, address),
      });
      const resp: TradeCommitResponse = await submitTrade(issuedQuote.quote_id, address, signature);
      const respJob = resp.relayer_job_id ? String(resp.relayer_job_id) : null;
      const respHash = resp.tx_hash || null;
      if (respHash || respJob) {
        const normalizedHash = normalizeTxHash(respHash) ?? respHash;
        setTxHash(normalizedHash || null);
        setRelayerJobId(respJob);
        setRelayerPendingSince(respJob && !normalizedHash ? Date.now() : null);
        const initialStatus = resp.relayer_status || (respHash ? "pending" : null);
        setTxStatus(initialStatus);
        setTxConfirmed(initialStatus === "confirmed");
      }
    } catch (err) {
      const message = sanitizeTradeErrorMessage(err);
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
        setTxError(message);
      }
    } finally {
      setTxLoading(false);
    }
  }, [
    address,
    capExhausted,
    chainId,
    chainMismatch,
    fxStale,
    fxUnavailable,
    marketId,
    normalizedMarketAddress,
    selectedOutcome,
    sanitizeTradeErrorMessage,
    signMessage,
    stakeOutOfRange,
    stakeZen,
    tradingDisabled,
    tradingReason,
  ]);

  // ── Effect: tx status polling ──────────────────────────────────────────
  useEffect(() => {
    if (!txHash && !relayerJobId) return;
    let cancelled = false;
    const pendingStart = relayerPendingSince;
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
            setRelayerPendingSince(null);
            return;
          }
        }
      } catch {
        // best effort
      }
      if (!cancelled && relayerJobId && !txHash && pendingStart && Date.now() - pendingStart > 60_000) {
        setTxError("Relayer is taking longer than expected. Please retry once.");
      }
      if (!cancelled) {
        setTimeout(poll, 5000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, [txHash, relayerJobId, relayerPendingSince]);

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div
      className={`self-start rounded-3xl border border-white/10 bg-slate-950/80 p-5 text-sm text-slate-100 backdrop-blur ${highlightClass}`}
    >
      {marketTitle && (
        <p className="text-sm font-semibold text-white/90">{marketTitle}</p>
      )}
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-lg font-semibold text-white">Buy {outcomeLabel}</p>
        </div>
      </div>

      <StakeInput
        outcomes={outcomes}
        outcomePrices={outcomePrices}
        selectedOutcome={selectedOutcome}
        stakeZen={stakeZen}
        ticketSize={TICKET_SIZE_ZEN}
        tradingDisabled={tradingDisabled}
        onOutcomeSelect={setSelectedOutcome}
      />

      <div className="mt-4 space-y-3">
        <QuoteDisplay
          quote={quote}
          toWinZen={toWinZen}
          stakeZen={stakeZen}
          quoteCountdown={quoteCountdown}
          shortQuoteId={shortQuoteId}
          quoteExpiryMs={quoteExpiryMs}
        />
      </div>

      <TradeSubmission
        ctaLabel={ctaLabel}
        submitBlockedReason={submitBlockedReason}
        disabled={ctaDisabled}
        onSubmit={handleTrade}
        txLoading={txLoading}
        txError={txError}
        txHash={txHash}
        txConfirmed={txConfirmed}
        txStatus={txStatus}
        relayerJobId={relayerJobId}
        explorerBase={explorerBase}
        error={error}
        stakeError={stakeError}
        escrowInsufficient={escrowInsufficient}
        fxStale={fxStale}
        capExhausted={capExhausted}
        chainMismatch={chainMismatch}
        chainName={defaultChain.name}
        expectedChainId={expectedChainId}
        tradingDisabled={tradingDisabled}
        tradingReason={tradingReason}
      />
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
