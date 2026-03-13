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

// ---------------------------------------------------------------------------
// Progress step types & logic
// ---------------------------------------------------------------------------

type StepState = "pending" | "active" | "done" | "error";

const STEP_LABELS = ["Wallet confirmation", "Submitting commit", "On-chain confirmation"] as const;

function getStepStates(
  txLoading: boolean,
  relayerJobId: string | null,
  txHashIsHex: boolean,
  txConfirmed: boolean,
  txStatus: string | null,
): [StepState, StepState, StepState] | null {
  if (txConfirmed) return ["done", "done", "done"];
  if (txStatus === "failed") {
    // Error on the most-recent active step
    if (txHashIsHex) return ["done", "done", "error"];
    if (relayerJobId) return ["done", "error", "pending"];
    return ["error", "pending", "pending"];
  }
  if (txHashIsHex) return ["done", "done", "active"];
  if (relayerJobId) return ["done", "active", "pending"];
  if (txLoading) return ["active", "pending", "pending"];
  return null; // no activity — hide indicator
}

// ---------------------------------------------------------------------------
// Step dot SVG components
// ---------------------------------------------------------------------------

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4">
      <circle cx="8" cy="8" r="8" className="fill-emerald-400" />
      <path d="M5 8.5l2 2 4-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ErrorIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4">
      <circle cx="8" cy="8" r="8" className="fill-rose-400" />
      <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function StepDot({ state }: { state: StepState }) {
  if (state === "done") return <CheckIcon />;
  if (state === "error") return <ErrorIcon />;
  return (
    <span
      className={`inline-block h-4 w-4 rounded-full border-2 ${
        state === "active"
          ? "animate-pulse border-emerald-400 bg-emerald-400"
          : "border-slate-600 bg-transparent"
      }`}
    />
  );
}

// ---------------------------------------------------------------------------
// ProgressSteps component
// ---------------------------------------------------------------------------

function ProgressSteps({ steps }: { steps: [StepState, StepState, StepState] }) {
  return (
    <div className="flex items-center gap-0 py-2" role="group" aria-label="Transaction progress">
      {steps.map((state, i) => (
        <div key={i} className="flex items-start" style={i < 2 ? { flex: "1 1 0%" } : undefined}>
          <div className="flex flex-col items-center gap-1">
            <StepDot state={state} />
            <span
              className={`text-center text-[10px] uppercase tracking-[0.15em] ${
                state === "error"
                  ? "text-rose-200"
                  : state === "done"
                    ? "text-emerald-200"
                    : state === "active"
                      ? "text-white"
                      : "text-slate-500"
              }`}
            >
              {STEP_LABELS[i]}
            </span>
          </div>
          {i < 2 && (
            <div className="flex flex-1 h-4 items-center min-w-3">
              <div
                className={`h-px flex-1 ${
                  state === "done" ? "bg-emerald-400" : "bg-slate-700"
                }`}
              />
              <svg
                viewBox="0 0 6 10"
                className={`h-2.5 w-1.5 shrink-0 -ml-px ${
                  state === "done" ? "text-emerald-400" : "text-slate-700"
                }`}
              >
                <path
                  d="M1 1l4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

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
  const relayerQueued = relayerJobId && !txHashIsHex && txStatus === "queued";
  const relayerFailed = relayerJobId && !txHashIsHex && (txStatus === "failed" || txStatus === "deadletter");

  const stepStates = getStepStates(txLoading, relayerJobId, txHashIsHex, txConfirmed, txStatus);

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
          Pricing temporarily paused. Please retry in a moment.
        </p>
      )}
      {capExhausted && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-amber-200">
          Maximum position size reached for this market. Try again later.
        </p>
      )}
      {chainMismatch && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-amber-200">
          Switch to {chainName} (chain {expectedChainId}) to trade.
        </p>
      )}
      {stepStates && !txConfirmed && <ProgressSteps steps={stepStates} />}
      {relayerQueued && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-300">
          Commit queued with relayer. Waiting for transaction hash.
        </p>
      )}
      {relayerJobId && !txHashIsHex && !relayerQueued && !relayerFailed && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-300">
          Waiting for the relayer to return the commit transaction hash.
        </p>
      )}
      {(relayerJobId || txHashIsHex) && !txConfirmed && (
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400">
          Track this commit in the{" "}
          <Link className="underline decoration-dotted" href="/dashboard">
            dashboard
          </Link>{" "}
          while it finalizes.
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
