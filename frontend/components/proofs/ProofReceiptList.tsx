import type { ProofReceipt } from "@/lib/api-types";
import { formatDateTime } from "@/lib/formatters";

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
  const statusLabel = receipt.proofHash ? "Proof cached" : "Receipt cached";
  const statusColor = receipt.proofHash
    ? "bg-emerald-500/20 text-emerald-100 border border-emerald-400/30"
    : "bg-amber-500/20 text-amber-100 border border-amber-300/30";
  const winningPool = receipt.winningPool ?? deriveWinningPool(receipt);
  const totalPool = receipt.totalPool ?? deriveTotalPool(receipt);
  const settlementTxHref = hrefFor("tx", receipt.settlementTxHash);

  return (
    <article className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 shadow-md shadow-black/40">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Proof request</p>
          <p className="font-mono text-sm text-white">{shorten(receipt.requestId ?? receipt.proofHash ?? "—")}</p>
        </div>
        <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${statusColor}`}>
          {statusLabel}
        </span>
      </div>

      <dl className="mt-6 grid gap-4 text-sm text-slate-300 md:grid-cols-2">
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Market</dt>
          <dd className="font-mono text-white">
            <ExplorerLink href={hrefFor("address", receipt.marketAddress)} label={receipt.marketAddress ?? "—"} />
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Condition</dt>
          <dd className="font-mono text-white">{shorten(receipt.conditionId ?? receipt.eventId ?? "—", 14)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Proof hash</dt>
          <dd className="font-mono text-white">{shorten(receipt.proofHash ?? "—", 14)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Circuit</dt>
          <dd className="font-mono text-white">
            {shorten(receipt.circuitHash ?? "—", 14)}
            {receipt.proverVersion ? <span className="text-slate-400"> (v{receipt.proverVersion})</span> : null}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Generated at</dt>
          <dd>{formatTimestamp(receipt.generatedAt)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Settlement tx</dt>
          <dd className="font-mono text-white">
            {settlementTxHref ? (
              <ExplorerLink href={settlementTxHref} label={receipt.settlementTxHash} />
            ) : (
              shorten(receipt.settlementTxHash, 10)
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Winning outcome</dt>
          <dd className="font-mono text-white">{receipt.winningOutcomeId ?? "—"}</dd>
        </div>
      </dl>

      <div className="mt-6 rounded-xl border border-white/10 bg-black/30 p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Settlement signals</p>
        <div className="mt-3 grid gap-3 text-sm text-slate-300 md:grid-cols-2">
          <Signal label="Winning pool" value={formatBigInt(winningPool)} />
          <Signal label="Total pool" value={formatBigInt(totalPool)} />
          <Signal label="Total liability" value={formatBigInt(receipt.totalLiability)} />
          <Signal label="Total escrow" value={formatBigInt(receipt.totalEscrow)} />
          <Signal label="Merkle root" value={shorten(receipt.merkleRoot, 12)} />
        </div>
      </div>

      {receipt.proof && (
        <div className="mt-4 rounded-xl border border-white/10 bg-black/30 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Proof (truncated)</p>
          <p className="font-mono text-xs text-slate-100 break-all">{shorten(receipt.proof, 24)}</p>
        </div>
      )}
    </article>
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

type ExplorerLinkProps = {
  href?: string | null;
  label?: string | null;
};

function ExplorerLink({ href, label }: ExplorerLinkProps) {
  const text = shorten(label, 10);
  if (!href) return <span>{text}</span>;
  return (
    <a className="text-brand-200 hover:text-brand-100 underline-offset-4 hover:underline" href={href} target="_blank" rel="noreferrer">
      {text}
    </a>
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
  return `${value.slice(0, visible)}…${value.slice(-visible)}`;
}

function formatTimestamp(timestamp?: string | null) {
  return formatDateTime(timestamp ?? undefined);
}

function formatBigInt(value?: string | null) {
  if (!value) return "—";
  try {
    const big = BigInt(value);
    const sign = big < 0 ? "-" : "";
    const digits = (sign === "-" ? -big : big).toString();
    return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  } catch {
    return value;
  }
}

function hrefFor(kind: "address" | "tx", value?: string | null) {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const base = explorerBase.replace(/\/+$/, "");
  return kind === "tx" ? `${base}/tx/${trimmed}` : `${base}/address/${trimmed}`;
}
