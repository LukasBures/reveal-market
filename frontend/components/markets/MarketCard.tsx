import type { MarketSummary } from "@/lib/api";
import Link from "next/link";

type Props = {
  market: MarketSummary;
};

function formatProbability(values?: number[]): string {
  if (!values || values.length === 0) return "—";
  const [yes] = values;
  return `${Math.round((yes ?? 0) * 100)}%`;
}

export function MarketCard({ market }: Props) {
  const yesProbability = formatProbability(market.outcomePrices);
  const outcomes = market.outcomes ?? [];
  const coverImage = market.imageUrl;

  return (
    <Link
      href={`/markets/${market.eventId}`}
      className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-slate-900/50 p-4 transition hover:border-brand-400/50 hover:bg-slate-900/80"
    >
      <div
        className="relative aspect-[16/9] w-full overflow-hidden rounded-xl border border-white/5"
        role="img"
        aria-label={coverImage ? `Artwork for ${market.title}` : `Placeholder artwork for ${market.title}`}
      >
        <div
          className={`h-full w-full ${coverImage ? "" : "bg-gradient-to-br from-brand-500/30 via-slate-800 to-slate-950"}`}
          style={
            coverImage
              ? {
                  backgroundImage: `url(${coverImage})`,
                  backgroundSize: "cover",
                  backgroundPosition: "center",
                }
              : undefined
          }
          aria-hidden="true"
        />
      </div>
      <div className="flex items-center justify-between text-xs uppercase tracking-[0.25em] text-slate-500">
        <span>{market.category ?? "General"}</span>
        <span>{market.status ?? "active"}</span>
      </div>
      <div>
        <h3 className="text-lg font-semibold text-white">{market.title}</h3>
        <p className="mt-1 text-sm text-slate-400">
          Commit closes{" "}
          {market.commitDeadline
            ? new Date(market.commitDeadline).toLocaleDateString()
            : "TBA"}
        </p>
      </div>
      <div className="flex items-center justify-between rounded-xl bg-white/5 px-4 py-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Yes probability</p>
          <p className="text-2xl font-semibold text-white">{yesProbability}</p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Liquidity</p>
          <p className="text-lg font-semibold text-brand-300">
            {market.liquidityUsd ? `$${Math.round(market.liquidityUsd).toLocaleString()}` : "—"}
          </p>
        </div>
      </div>
      {outcomes.length > 0 && (
        <div className="space-y-2 text-sm">
          {outcomes.slice(0, 3).map((outcome, idx) => (
            <div key={outcome} className="flex items-center justify-between rounded-lg bg-slate-950/60 px-3 py-2">
              <span className="text-slate-300">{outcome}</span>
              <span className="font-semibold text-white">
                {market.outcomePrices?.[idx]
                  ? `${Math.round((market.outcomePrices[idx] ?? 0) * 100)}%`
                  : "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Link>
  );
}
