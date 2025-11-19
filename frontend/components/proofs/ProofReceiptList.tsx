import type { ProofReceipt } from "@/lib/api-types";
import { formatDateTime } from "@/lib/formatters";

type Props = {
  receipts: ProofReceipt[];
};

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
      {receipts.map((receipt) => (
        <ProofReceiptCard key={receipt.proofNonce} receipt={receipt} />
      ))}
    </div>
  );
}

type CardProps = {
  receipt: ProofReceipt;
};

function ProofReceiptCard({ receipt }: CardProps) {
  const statusColor =
    receipt.status === "verified"
      ? "bg-emerald-500/20 text-emerald-200 border border-emerald-400/30"
      : "bg-rose-500/20 text-rose-200 border border-rose-400/30";

  return (
    <article className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 shadow-md shadow-black/40">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Proof nonce</p>
          <p className="font-mono text-sm text-white">{receipt.proofNonce}</p>
        </div>
        <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${statusColor}`}>
          {receipt.status === "verified" ? "On-chain verified" : "Rejected"}
        </span>
      </div>

      <dl className="mt-6 grid gap-4 text-sm text-slate-300 md:grid-cols-2">
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Market</dt>
          <dd className="font-mono text-white">{shorten(receipt.marketAddress)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Verifier</dt>
          <dd className="font-mono text-white">{shorten(receipt.verifier)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Tx hash</dt>
          <dd className="font-mono text-white">{shorten(receipt.transactionHash, 10)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">Verified at</dt>
          <dd>{formatTimestamp(receipt.verifiedAt)}</dd>
        </div>
        {receipt.zkVerifyReceipt && (
          <div>
            <dt className="text-xs uppercase tracking-[0.3em] text-slate-400">zkVerify receipt</dt>
            <dd className="font-mono text-brand-200">{receipt.zkVerifyReceipt}</dd>
          </div>
        )}
      </dl>

      <div className="mt-6 rounded-xl border border-white/10 bg-black/30 p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-400">Public signals</p>
        <div className="mt-3 grid gap-3 text-sm text-slate-300 md:grid-cols-2">
          <Signal label="Winning pool" value={formatBigInt(receipt.winningPool)} />
          <Signal label="Total pool" value={formatBigInt(receipt.totalPool)} />
          <Signal label="Outcome hash" value={shorten(receipt.outcomeHash, 12)} />
          <Signal label="Circuit version" value={`v${receipt.circuitVersion}`} />
        </div>
      </div>
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

function shorten(value: string, visible = 6): string {
  if (!value) {
    return "—";
  }
  if (value.length <= visible * 2) {
    return value;
  }
  return `${value.slice(0, visible)}…${value.slice(-visible)}`;
}

function formatTimestamp(timestamp?: string) {
  return formatDateTime(timestamp);
}

function formatBigInt(value: string) {
  try {
    const big = BigInt(value);
    const sign = big < 0 ? "-" : "";
    const digits = (sign === "-" ? -big : big).toString();
    return sign + digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  } catch {
    return value;
  }
}
