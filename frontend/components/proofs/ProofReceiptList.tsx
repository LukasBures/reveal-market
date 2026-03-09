"use client";

import { useState, type ReactNode } from "react";
import type { ProofReceipt } from "@/lib/api-types";
import { formatDateTime, normalizeHex } from "@/lib/formatters";
import { CopyButton } from "@/components/ui/CopyButton";

type Props = {
  receipts: ProofReceipt[];
};

const explorerBase = process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL ?? "https://horizen.calderaexplorer.xyz";

export function ProofReceiptList({ receipts }: Props) {
  if (!receipts.length) {
    return (
      <p className="rounded-2xl border border-white/10 bg-white/5 px-6 py-10 text-center text-slate-300">
        No proof receipts have been recorded yet.
      </p>
    );
  }

  return (
    <div className="grid gap-4">
      {receipts.map((receipt, index) => (
        <ProofReceiptCard
          key={receipt.requestId ?? receipt.proofHash ?? receipt.marketAddress ?? `${receipt.conditionId}-${index}`}
          receipt={receipt}
        />
      ))}
    </div>
  );
}

type CardProps = {
  receipt: ProofReceipt;
};

function ProofReceiptCard({ receipt }: CardProps) {
  const [open, setOpen] = useState(false);

  const batchIndex = typeof receipt.batchIndex === "number" ? receipt.batchIndex : null;
  const batchNumber = batchIndex !== null ? batchIndex + 1 : null;
  const batchLabel = batchNumber !== null ? `Batch ${batchNumber}` : null;
  const rootLabel = batchNumber !== null ? "Batch root" : "Merkle root";
  const winningPool = receipt.winningPool ?? deriveWinningPool(receipt);
  const totalPool = receipt.totalPool ?? deriveTotalPool(receipt);
  const settlementTxDisplay = normalizeHex(receipt.settlementTxHash) ?? receipt.settlementTxHash ?? null;
  const settlementTxHref = hrefFor("tx", settlementTxDisplay);
  const winningPoolDisplay = formatZen(winningPool);
  const totalPoolDisplay = formatZen(totalPool);
  const liabilityDisplay = formatZen(receipt.totalLiability);
  const escrowDisplay = formatZen(receipt.totalEscrow);

  const outcomeId = receipt.winningOutcomeId;
  const outcomeBadge =
    outcomeId === 0
      ? { label: "YES won", cls: "bg-emerald-500/20 border border-emerald-400/50 text-emerald-200" }
      : outcomeId === 1
        ? { label: "NO won", cls: "bg-rose-500/20 border border-rose-400/30 text-rose-300" }
        : null;

  const detailItems: DetailItem[] = [
    { label: "Request ID", value: receipt.requestId },
    { label: "Market address", value: receipt.marketAddress },
    { label: "Settlement transaction", value: settlementTxDisplay },
    { label: "Proof hash", value: receipt.proofHash },
    { label: "Circuit hash", value: receipt.circuitHash },
    { label: "Prover build", value: receipt.proverVersion },
    { label: rootLabel, value: receipt.merkleRoot },
    { label: "Batch", value: batchNumber !== null ? String(batchNumber) : null },
    {
      label: receipt.publicSignals?.length ? `Public signals (${receipt.publicSignals.length})` : null,
      value: receipt.publicSignals?.join(", "),
    },
    {
      label: receipt.proof ? "Proof payload (truncated)" : null,
      value: receipt.proof ? shorten(receipt.proof, 48) : null,
    },
  ].filter((item): item is DetailItem => Boolean(item.label && item.value));

  return (
    <article className="rounded-3xl border border-[#7c84ff]/15 bg-slate-950/40 p-5 shadow-[0_0_28px_rgba(12,39,177,0.12)]">
      {/* Header row — at a glance */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        {/* Left: ID + timestamp */}
        <div className="min-w-0 space-y-1">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Proof receipt</p>
          <span className="inline-flex items-center gap-1.5">
            <span className="font-mono text-sm text-white" title={receipt.requestId ?? undefined}>
              {shorten(receipt.requestId ?? receipt.proofHash ?? "—", 10)}
            </span>
            {receipt.requestId ?? receipt.proofHash ? (
              <CopyButton value={receipt.requestId ?? receipt.proofHash ?? ""} label="Copy request ID" />
            ) : null}
          </span>
          <p className="text-xs text-slate-500">{formatTimestamp(receipt.generatedAt)}</p>
        </div>

        {/* Right: outcome badge + winning pool + settlement TX */}
        <div className="flex flex-wrap items-center gap-3">
          {outcomeBadge ? (
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${outcomeBadge.cls}`}>
              {outcomeBadge.label}
            </span>
          ) : null}
          {winningPool ? (
            <span className="font-mono text-lg font-semibold text-accent-400">{winningPoolDisplay}</span>
          ) : null}
          {batchLabel ? (
            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-xs text-slate-400">
              {batchLabel}
            </span>
          ) : null}
          {settlementTxHref ? (
            <a
              href={settlementTxHref}
              target="_blank"
              rel="noreferrer"
              title={settlementTxDisplay ?? "Settlement transaction"}
              className="flex cursor-pointer items-center gap-1 text-xs text-brand-200 transition-colors hover:text-brand-100"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="h-3.5 w-3.5">
                <path d="M6.22 8.72a.75.75 0 0 0 1.06 1.06l5.22-5.22v1.69a.75.75 0 0 0 1.5 0v-3.5a.75.75 0 0 0-.75-.75h-3.5a.75.75 0 0 0 0 1.5h1.69L6.22 8.72Z" />
                <path d="M3.5 6.75c0-.69.56-1.25 1.25-1.25H7A.75.75 0 0 0 7 4H4.75A2.75 2.75 0 0 0 2 6.75v4.5A2.75 2.75 0 0 0 4.75 14h4.5A2.75 2.75 0 0 0 12 11.25V9a.75.75 0 0 0-1.5 0v2.25c0 .69-.56 1.25-1.25 1.25h-4.5c-.69 0-1.25-.56-1.25-1.25v-4.5Z" />
              </svg>
              Tx
            </a>
          ) : null}
        </div>
      </div>

      {/* Body — 3 essential fields always visible */}
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
        <DataCell label="Market">
          <ExplorerLink href={hrefFor("address", receipt.marketAddress)} label={receipt.marketAddress ?? "—"} />
        </DataCell>
        <DataCell label="Condition">
          <TruncatedValue value={receipt.conditionId ?? receipt.eventId} visible={12} copyable />
        </DataCell>
        <DataCell label={rootLabel}>
          <TruncatedValue value={receipt.merkleRoot} visible={14} copyable />
        </DataCell>
      </dl>

      {/* Accordion toggle */}
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="mt-4 flex cursor-pointer items-center gap-1.5 text-xs uppercase tracking-[0.3em] text-slate-400 transition-colors hover:text-slate-300"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 16 16"
          fill="currentColor"
          className={`h-3.5 w-3.5 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        >
          <path
            fillRule="evenodd"
            d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
            clipRule="evenodd"
          />
        </svg>
        Details
      </button>

      {/* Accordion content */}
      {open ? (
        <div className="mt-3 space-y-3">
          {/* Settlement signals */}
          <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Settlement signals</p>
            <div className="mt-3 grid gap-3 text-sm text-slate-300 sm:grid-cols-2 xl:grid-cols-4">
              <Signal label="Winning pool" value={winningPoolDisplay} />
              <Signal label="Total pool" value={totalPoolDisplay} />
              <Signal label="Total liability" value={liabilityDisplay} />
              <Signal label="Total escrow" value={escrowDisplay} />
            </div>
          </div>

          {/* Technical fields */}
          <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Technical</p>
            <div className="mt-3 grid gap-3 text-xs text-slate-300 sm:grid-cols-2">
              {receipt.proofHash ? (
                <TechCell label="Proof hash">
                  <TruncatedValue value={receipt.proofHash} visible={14} copyable />
                </TechCell>
              ) : null}
              {receipt.circuitHash ? (
                <TechCell label="Circuit hash">
                  <span className="font-mono text-white" title={receipt.circuitHash ?? undefined}>
                    {shorten(receipt.circuitHash, 14)}
                  </span>
                </TechCell>
              ) : null}
              {receipt.proverVersion ? (
                <TechCell label="Prover build">
                  <TruncatedValue value={receipt.proverVersion} visible={12} copyable />
                </TechCell>
              ) : null}
              {outcomeId != null ? (
                <TechCell label="Winning outcome id">
                  <span className="font-mono text-white">{outcomeId}</span>
                </TechCell>
              ) : null}
              {batchNumber !== null ? (
                <TechCell label="Batch number">
                  <span className="font-mono text-white">{batchNumber}</span>
                </TechCell>
              ) : null}
            </div>
          </div>

          {/* Full untruncated values */}
          {detailItems.length ? (
            <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Full values</p>
              <div className="mt-3 space-y-3 text-sm text-slate-300">
                {detailItems.map((item) => (
                  <DetailRow key={item.label} label={item.label ?? ""} value={item.value ?? ""} />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

type DataCellProps = {
  label: string;
  children: ReactNode;
};

function DataCell({ label, children }: DataCellProps) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">{label}</dt>
      <dd className="font-mono text-white">{children}</dd>
    </div>
  );
}

type TechCellProps = {
  label: string;
  children: ReactNode;
};

function TechCell({ label, children }: TechCellProps) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{label}</p>
      <div className="mt-0.5 font-mono text-xs text-white">{children}</div>
    </div>
  );
}

type SignalProps = {
  label: string;
  value: string;
};

function Signal({ label, value }: SignalProps) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{label}</p>
      <p className="font-mono text-sm text-white">{value}</p>
    </div>
  );
}

type DetailRowProps = {
  label: string;
  value: string;
};

function DetailRow({ label, value }: DetailRowProps) {
  return (
    <div>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{label}</p>
      <p className="break-all font-mono text-xs text-white">{value}</p>
    </div>
  );
}

type ExplorerLinkProps = {
  href?: string | null;
  label?: string | null;
  visible?: number;
};

function ExplorerLink({ href, label, visible = 10 }: ExplorerLinkProps) {
  const text = shorten(label, visible);
  return (
    <span className="inline-flex items-center gap-1">
      {href ? (
        <a
          className="text-brand-200 underline-offset-4 hover:text-brand-100 hover:underline"
          href={href}
          target="_blank"
          rel="noreferrer"
          title={label ?? undefined}
        >
          {text}
        </a>
      ) : (
        <span title={label ?? undefined}>{text}</span>
      )}
      {label ? <CopyButton value={label} label="Copy address" /> : null}
    </span>
  );
}

type DetailItem = {
  label: string;
  value: string;
};

type TruncatedValueProps = {
  value?: string | null;
  visible?: number;
  copyable?: boolean;
};

function TruncatedValue({ value, visible = 10, copyable = false }: TruncatedValueProps) {
  const display = shorten(value, visible);
  if (display === "—") {
    return <span>—</span>;
  }
  return (
    <span className="inline-flex items-center gap-1">
      <span title={value ?? undefined} className="font-mono text-white">
        {display}
      </span>
      {copyable && value ? <CopyButton value={value} label="Copy value" /> : null}
    </span>
  );
}

function deriveWinningPool(receipt: ProofReceipt): string | undefined {
  if (receipt.winningOutcomeId === 0) {
    return receipt.poolTotalYes ?? receipt.winningPool ?? undefined;
  }
  if (receipt.winningOutcomeId === 1) {
    return receipt.poolTotalNo ?? receipt.winningPool ?? undefined;
  }
  return receipt.winningPool ?? undefined;
}

function deriveTotalPool(receipt: ProofReceipt): string | undefined {
  if (receipt.totalPool) return receipt.totalPool;
  if (receipt.totalEscrow) return receipt.totalEscrow;
  if (receipt.poolTotalYes && receipt.poolTotalNo) {
    try {
      return (BigInt(receipt.poolTotalYes) + BigInt(receipt.poolTotalNo)).toString();
    } catch {
      return undefined;
    }
  }
  return undefined;
}

function shorten(value?: string | null, visible = 6): string {
  if (!value) {
    return "—";
  }
  if (value.length <= visible * 2) {
    return value;
  }
  return `${value.slice(0, visible)}...${value.slice(-visible)}`;
}

function formatZen(value?: string | null) {
  if (!value) return "—";
  let raw: bigint;
  try {
    raw = BigInt(value);
  } catch {
    return value;
  }
  const sign = raw < 0n ? "-" : "";
  const abs = raw < 0n ? -raw : raw;
  const base = 10n ** 18n;
  const integer = abs / base;
  const fraction = abs % base;
  let fractionStr = fraction.toString().padStart(18, "0").slice(0, 4);
  fractionStr = fractionStr.replace(/0+$/, "");
  const integerStr = formatWhole(integer);
  const display = fractionStr ? `${integerStr}.${fractionStr}` : integerStr;
  return `${sign}${display} ZEN`;
}

function formatWhole(value: bigint) {
  const digits = value.toString();
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function formatTimestamp(timestamp?: string | null) {
  return formatDateTime(timestamp ?? undefined);
}

function hrefFor(kind: "address" | "tx", value?: string | null) {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const base = explorerBase.replace(/\/+$/, "");
  if (kind === "tx") {
    const normalized = normalizeHex(trimmed);
    if (!normalized) return null;
    return `${base}/tx/${normalized}`;
  }
  return `${base}/address/${trimmed}`;
}
