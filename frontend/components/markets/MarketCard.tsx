import type { MarketSummary } from "@/lib/api-types";
import Link from "next/link";
import Image from "next/image";

type Props = {
  market: MarketSummary;
};

const currencyFormatter = Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function formatProbability(values?: number[]): string {
  if (!values || values.length === 0) return "—";
  const [yes] = values;
  return `${Math.round((yes ?? 0) * 100)}%`;
}

function formatLiquidity(value?: number | null): string {
  if (!value || Number.isNaN(value)) {
    return "—";
  }
  return currencyFormatter.format(value);
}

export function MarketCard({ market }: Props) {
  const yesProbability = formatProbability(market.outcomePrices);
  const outcomes = market.outcomes ?? [];
  const coverImage = market.imageUrl;

  return (
    <Link
      href={`/markets/${market.eventId}`}
      className="group relative flex h-full flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 shadow-xl shadow-black/30 transition duration-200 hover:-translate-y-1 hover:border-brand-400/60 hover:bg-white/10"
    >
      <div className="relative aspect-[16/9] w-full overflow-hidden rounded-xl border border-white/5">
        {coverImage ? (
          <Image
            src={coverImage}
            alt={`Artwork for ${market.title}`}
            fill
            sizes="(max-width: 640px) 100vw, (max-width: 1280px) 50vw, 25vw"
            className="object-cover transition duration-500 group-hover:scale-105"
            priority={false}
            loading="lazy"
          />
        ) : (
          <div className="h-full w-full bg-gradient-to-br from-brand-500/30 via-slate-800 to-slate-950" aria-hidden="true" />
        )}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />
        <span className="absolute left-4 top-4 rounded-full bg-white/10 px-3 py-1 text-xs uppercase tracking-[0.3em] text-white/80">
          {market.category ?? "General"}
        </span>
      </div>
      <div className="flex items-center justify-between text-[0.65rem] uppercase tracking-[0.35em] text-slate-500">
        <span>{market.status ?? "active"}</span>
        <span>{market.commitDeadline ? new Date(market.commitDeadline).toLocaleDateString() : "Commit window"}</span>
      </div>
      <h3 className="text-lg font-semibold text-white">{market.title}</h3>
      <div className="flex items-center justify-between rounded-xl bg-slate-950/60 px-3 py-2 text-sm">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Yes probability</p>
          <p className="text-2xl font-semibold text-white">{yesProbability}</p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Liquidity</p>
          <p className="text-xl font-semibold text-brand-200">{formatLiquidity(market.liquidityUsd)}</p>
        </div>
      </div>
      {outcomes.length > 0 && (
        <div className="mt-1 space-y-1 text-xs text-slate-300">
          {outcomes.slice(0, 2).map((outcome, idx) => (
            <div key={outcome} className="flex items-center justify-between rounded-lg bg-slate-900/60 px-3 py-1.5">
              <span className="truncate">{outcome}</span>
              <span className="font-semibold text-white">
                {market.outcomePrices?.[idx]
                  ? `${Math.round((market.outcomePrices[idx] ?? 0) * 100)}%`
                  : idx === 0
                    ? yesProbability
                    : "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Link>
  );
}
