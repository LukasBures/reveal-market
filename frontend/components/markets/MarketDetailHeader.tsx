import type { MarketDetail } from "@/lib/api";

type Props = {
  market: MarketDetail;
};

export function MarketDetailHeader({ market }: Props) {
  return (
    <header className="rounded-3xl border border-white/10 bg-slate-900/70 p-6 shadow-lg shadow-black/30">
      <p className="text-center text-xs uppercase tracking-[0.3em] text-slate-500 md:text-left">
        {market.category ?? "Market"}
      </p>
      <div className="mt-2 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="text-center md:text-left">
          <h1 className="text-3xl font-semibold text-white md:text-[2.75rem]">{market.title}</h1>
          <p className="text-sm text-slate-400">
            Last updated {market.updatedAt ? new Date(market.updatedAt).toLocaleString() : "recently"}
          </p>
        </div>
        <div className="grid gap-3 rounded-2xl border border-white/10 bg-slate-950/60 px-4 py-4 text-sm text-slate-300 md:min-w-[260px] md:px-6">
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.3em] text-slate-500">
            <span>Commit close</span>
            <span className="text-base font-semibold text-white">
              {market.commitDeadline ? new Date(market.commitDeadline).toLocaleDateString() : "TBA"}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.3em] text-slate-500">
            <span>Reveal close</span>
            <span className="text-base font-semibold text-white">
              {market.revealDeadline ? new Date(market.revealDeadline).toLocaleDateString() : "TBA"}
            </span>
          </div>
          <div className="flex items-center justify-between text-xs uppercase tracking-[0.3em] text-slate-500">
            <span>Status</span>
            <span className="rounded-full bg-emerald-500/20 px-3 py-1 text-xs font-semibold text-emerald-300">
              {market.status ?? "active"}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
