import type { ReactNode } from "react";
import type { ProofReceipt } from "@/lib/api-types";
import { formatDateTime, normalizeHex } from "@/lib/formatters";

type Props = {
  receipts: ProofReceipt[];
};

const explorerBase = process.env.NEXT_PUBLIC_BLOCK_EXPLORER_URL ?? "https://horizen-testnet.explorer.caldera.xyz";

export function ProofReceiptList({ receipts }: Props) {
  if (!receipts.length) {
    return (
      <p className="rounded-2xl border border-white/10 bg-white/5 px-6 py-10 text-center text-slate-300">
        No proof receipts have been recorded yet.
      </p>
    );
  }

  return (
    <div className="grid gap-6">
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
  const detailItems: DetailItem[] = [
    { label: "Request id", value: receipt.requestId },
    { label: "Market address", value: receipt.marketAddress },
    { label: "Settlement tx", value: settlementTxDisplay },
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
    <article className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 shadow-md shadow-black/40">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Proof receipt</p>
          <p className="font-mono text-sm text-white" title={receipt.requestId ?? undefined}>
            {shorten(receipt.requestId ?? receipt.proofHash ?? "—", 10)}
          </p>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span>{formatTimestamp(receipt.generatedAt)}</span>
            {batchLabel ? <span>{batchLabel}</span> : null}
          </div>
        </div>
        <div className="flex flex-col items-start gap-2 md:items-end">
          <div className="text-xs uppercase tracking-[0.3em] text-slate-500">Settlement tx</div>
          <div className="font-mono text-sm text-white">
            {settlementTxHref ? (
              <ExplorerLink href={settlementTxHref} label={settlementTxDisplay} />
            ) : (
              <span title={settlementTxDisplay ?? undefined}>{shorten(settlementTxDisplay, 10)}</span>
            )}
          </div>
        </div>
      </div>

      <dl className="mt-6 grid gap-4 text-sm text-slate-300 md:grid-cols-3">
        <DataCell label="Market">
          <ExplorerLink href={hrefFor("address", receipt.marketAddress)} label={receipt.marketAddress ?? "—"} />
        </DataCell>
        <DataCell label="Condition">
          <TruncatedValue value={receipt.conditionId ?? receipt.eventId} visible={12} />
        </DataCell>
        <DataCell label="Winning outcome">
          <span className="font-mono text-white">{receipt.winningOutcomeId ?? "—"}</span>
        </DataCell>
        <DataCell label="Proof hash">
          <TruncatedValue value={receipt.proofHash} visible={14} />
        </DataCell>
        <DataCell label="Circuit">
          <span className="font-mono text-white" title={receipt.circuitHash ?? undefined}>
            {shorten(receipt.circuitHash ?? "—", 14)}
          </span>
        </DataCell>
        <DataCell label="Prover build">
          <TruncatedValue value={receipt.proverVersion} visible={12} />
        </DataCell>
        <DataCell label={rootLabel}>
          <TruncatedValue value={receipt.merkleRoot} visible={14} />
        </DataCell>
        {batchNumber !== null ? (
          <DataCell label="Batch">
            <span className="font-mono text-white">{batchNumber}</span>
          </DataCell>
        ) : null}
      </dl>

      <div className="mt-6 rounded-xl border border-white/10 bg-black/30 p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Settlement signals</p>
        <div className="mt-3 grid gap-3 text-sm text-slate-300 md:grid-cols-2 xl:grid-cols-4">
          <Signal label="Winning pool" value={winningPoolDisplay} />
          <Signal label="Total pool" value={totalPoolDisplay} />
          <Signal label="Total liability" value={liabilityDisplay} />
          <Signal label="Total escrow" value={escrowDisplay} />
        </div>
      </div>

      {detailItems.length ? (
        <details className="mt-4 rounded-xl border border-white/10 bg-black/30 p-4">
          <summary className="cursor-pointer text-xs uppercase tracking-[0.3em] text-slate-400">
            Full receipt values
          </summary>
          <div className="mt-3 space-y-3 text-sm text-slate-300">
            {detailItems.map((item) => (
              <DetailRow key={item.label} label={item.label ?? ""} value={item.value ?? ""} />
            ))}
          </div>
        </details>
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
      <p className="font-mono text-xs text-white break-all">{value}</p>
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
  if (!href) return <span>{text}</span>;
  return (
    <a
      className="text-brand-200 hover:text-brand-100 underline-offset-4 hover:underline"
      href={href}
      target="_blank"
      rel="noreferrer"
      title={label ?? undefined}
    >
      {text}
    </a>
  );
}

type DetailItem = {
  label: string;
  value: string;
};

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
  return `${value.slice(0, visible)}…${value.slice(-visible)}`;
}

type TruncatedValueProps = {
  value?: string | null;
  visible?: number;
};

function TruncatedValue({ value, visible = 10 }: TruncatedValueProps) {
  const display = shorten(value, visible);
  if (display === "—") {
    return <span>—</span>;
  }
  return (
    <span title={value ?? undefined} className="font-mono text-white">
      {display}
    </span>
  );
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
  const precision = integer === 0n ? 6 : 4;
  let fractionStr = fraction.toString().padStart(18, "0").slice(0, precision);
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
