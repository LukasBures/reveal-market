import type { MarketDetail } from "@/lib/api-types";

type Props = {
  market: MarketDetail;
};

export function MarketDetailOutcomes({ market }: Props) {
  const outcomes = market.outcomes ?? [];

  if (outcomes.length === 0) {
    return (
      <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-slate-400">
        No outcome data available.
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/40 p-4 sm:p-6">
      <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-sm text-slate-200">
        <thead>
          <tr className="text-left text-xs uppercase tracking-[0.25em] text-slate-500">
            <th className="py-2">Outcome</th>
            <th className="py-2">Chance</th>
            <th className="py-2 text-right">Quote</th>
          </tr>
        </thead>
        <tbody>
          {outcomes.map((outcome, idx) => (
            <tr key={outcome} className="border-t border-white/5">
              <td className="py-3 font-semibold text-white">{outcome}</td>
              <td className="py-3 text-slate-300">
                {market.outcomePrices?.[idx]
                  ? `${Math.round((market.outcomePrices[idx] ?? 0) * 100)}%`
                  : "—"}
              </td>
              <td className="py-3 text-right">
                <button className="rounded-full bg-brand-500/80 px-4 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-white hover:bg-brand-500">
                  Trade
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
