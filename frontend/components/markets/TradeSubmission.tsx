"use client";

import Link from "next/link";
import { normalizeTxHash } from "@/lib/formatters";

type TradeSubmissionProps = {
  /** The label shown on the primary CTA (e.g. "Buy Yes with 0.10 ZEN"). */
  ctaLabel: string;
  /** When non-null, replaces `ctaLabel` with a reason the button is blocked. */
  submitBlockedReason: string | null;
  /** Whether the CTA is disabled. */
  disabled: boolean;
  /** Fires when the user clicks the CTA. */
  onSubmit: () => void;
  // --- tx state ---
  txLoading: boolean;
  txError: string | null;
  txHash: string | null;
  txConfirmed: boolean;
  txStatus: string | null;
  relayerJobId: string | null;
  // --- contextual display ---
  explorerBase: string;
  error: string | null;
  stakeError: string | null;
  escrowInsufficient: boolean;
  fxStale: boolean;
  capExhausted: boolean;
  chainMismatch: boolean;
  chainName: string;
  expectedChainId: number;
  tradingDisabled: boolean;
  tradingReason: string | null;
};

const shortenHash = (hash?: string | null): string | null => {
  if (!hash) return null;
  const trimmed = hash.trim();
  if (!trimmed) return null;
  if (trimmed.length <= 16) return trimmed;
  return `${trimmed.slice(0, 10)}...${trimmed.slice(-6)}`;
};

export function TradeSubmission({
  ctaLabel,
  submitBlockedReason,
  disabled,
  onSubmit,
  txLoading,
  txError,
  txHash,
  txConfirmed,
  txStatus,
  relayerJobId,
  explorerBase,
  error,
  stakeError,
  escrowInsufficient,
  fxStale,
  capExhausted,
  chainMismatch,
  chainName,
  expectedChainId,
  tradingDisabled,
  tradingReason,
}: TradeSubmissionProps) {
  const normalizedTxHash = normalizeTxHash(txHash);
  const txHashIsHex = Boolean(normalizedTxHash);
  const txHashDisplay = normalizedTxHash ?? (typeof txHash === "string" ? txHash.trim() : "");

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

  return (
    <div className="mt-4 flex flex-col gap-2">
      {tradingDisabled && tradingReason !== "Market settled" && (
        <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          {tradingReason ?? "Trading is unavailable for this market."}
        </div>
      )}

      <button
        type="button"
        disabled={disabled}
        onClick={onSubmit}
        className={`inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold uppercase tracking-[0.2em] transition ${
          disabled
            ? "cursor-not-allowed bg-white/20 text-white/60"
            : "bg-emerald-500 text-white hover:bg-emerald-400"
        }`}
      >
        {submitBlockedReason ?? ctaLabel}
      </button>

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
          Switch to {chainName} (chain {expectedChainId}) to trade.
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
              {shortenHash(txHashDisplay)}
            </a>
          ) : (
            shortenHash(txHashDisplay)
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
  );
}
