import type { MarketDetail } from "@/lib/api";
import Link from "next/link";

type Props = {
  market: MarketDetail;
};

function formatDate(input?: string | null) {
  return input ? new Date(input).toLocaleString() : "—";
}

export function MarketDetailSidebar({ market }: Props) {
  const resolution = market.resolution ?? (market.extraData?.resolution as any);
  const tags = market.tags ?? [];

  return (
    <aside className="space-y-6 rounded-3xl border border-white/10 bg-slate-900/70 p-6">
      <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
        <div className="flex items-center justify-between">
          <span>Category</span>
          <span className="font-semibold text-white">{market.category ?? "General"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Status</span>
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              resolution?.resolved ? "bg-emerald-500/20 text-emerald-300" : "bg-brand-500/20 text-brand-200"
            }`}
          >
            {resolution?.resolved ? "Resolved" : market.status ?? "Active"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Created</span>
          <span className="text-white">{formatDate(market.createdAt)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Liquidity</span>
          <span className="text-white">
            {market.liquidityUsd ? `$${Math.round(market.liquidityUsd).toLocaleString()}` : "—"}
          </span>
        </div>
      </div>
      <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
        <div className="flex items-center justify-between">
          <span>Commit deadline</span>
          <span className="text-white">{formatDate(market.commitDeadline)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Reveal deadline</span>
          <span className="text-white">{formatDate(market.revealDeadline)}</span>
        </div>
        {tags.length > 0 && (
          <div>
            <span className="text-xs uppercase tracking-[0.3em] text-slate-500">Tags</span>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {tags.map((tag) => (
                <span key={tag} className="rounded-full bg-brand-500/15 px-3 py-1 text-brand-200">
                  #{tag}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      {resolution && (
        <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-5 text-sm text-slate-300">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Settlement proof</p>
          <p className="mt-2">Checked at {formatDate(resolution.checkedAt)}</p>
          {resolution.transactionHash && (
            <p className="mt-2 break-all text-xs text-slate-500">TX: {resolution.transactionHash}</p>
          )}
          {resolution.blockNumber && (
            <p className="text-xs text-slate-500">Block #{resolution.blockNumber}</p>
          )}
        </div>
      )}
      <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Documentation</p>
        <ul className="mt-3 space-y-2 text-sm text-slate-300">
          <li>
            <Link href="/docs/architecture" className="text-brand-300 hover:underline">
              Market architecture guide
            </Link>
          </li>
          <li>
            <Link href="/docs/privacy-security" className="text-brand-300 hover:underline">
              Risk controls
            </Link>
          </li>
          <li>
            <Link href="/docs/tokenomics" className="text-brand-300 hover:underline">
              Rake and incentives
            </Link>
          </li>
        </ul>
      </div>
    </aside>
  );
}
