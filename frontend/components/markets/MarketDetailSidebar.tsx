import type { MarketDetail } from "@/lib/api";
import Link from "next/link";

type Props = {
  market: MarketDetail;
};

export function MarketDetailSidebar({ market }: Props) {
  return (
    <aside className="space-y-6 rounded-3xl border border-white/10 bg-slate-900/70 p-6">
      <div className="rounded-2xl border border-white/10 bg-gradient-to-b from-slate-900 to-slate-950 p-5 text-center">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Position size</p>
        <p className="mt-3 text-3xl font-semibold text-white">$0</p>
        <div className="mt-4 flex justify-center gap-3 text-xs text-slate-400">
          {["+1", "+10", "+100"].map((step) => (
            <button key={step} className="rounded-full border border-white/10 px-3 py-1 hover:border-brand-400">
              {step}
            </button>
          ))}
        </div>
        <button className="mt-4 w-full rounded-full bg-brand-500 py-3 font-semibold text-white shadow-glow-brand transition hover:bg-brand-400">
          Connect to trade
        </button>
        <p className="mt-2 text-xs text-slate-500">Integrate with the worker to auto-settle.</p>
      </div>
      <div className="space-y-3 rounded-2xl border border-white/10 bg-slate-950/50 p-5 text-sm text-slate-300">
        <div className="flex items-center justify-between">
          <span>Oracle</span>
          <span className="font-semibold text-white">{market.oracle ?? "Reveal Market"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Created</span>
          <span className="text-white">
            {market.createdAt ? new Date(market.createdAt).toLocaleDateString() : "—"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span>Liquidity</span>
          <span className="text-white">
            {market.liquidityUsd ? `$${Math.round(market.liquidityUsd).toLocaleString()}` : "—"}
          </span>
        </div>
      </div>
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
