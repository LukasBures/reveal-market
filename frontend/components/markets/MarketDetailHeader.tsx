import type { MarketDetail } from "@/lib/api-types";
import Link from "next/link";
import { MarketArtwork } from "./MarketArtwork";
import { formatDate, formatDateTime } from "@/lib/formatters";

type Props = {
  market: MarketDetail;
  coverImage?: string;
};

const formatZenPrice = (value: number | null): string => {
  if (value === null) return "—";
  return `${value.toFixed(3)} ZEN`;
};

export function MarketDetailHeader({ market, coverImage }: Props) {
  const yesPrice = typeof market.outcomePrices?.[0] === "number" ? market.outcomePrices[0] : null;
  const yesProbability = yesPrice !== null ? Math.round(yesPrice * 100) : null;
  const noProbability = yesProbability !== null ? Math.max(0, 100 - yesProbability) : null;
  const noPrice = yesPrice !== null ? Math.max(0, 1 - yesPrice) : null;
  const yesLabel = market.outcomes?.[0] ?? "Yes";
  const noLabel = market.outcomes?.[1] ?? "No";

  return (
    <header className="rounded-3xl border border-white/10 bg-gradient-to-r from-slate-950/90 via-slate-950/80 to-slate-900/80 p-6 shadow-lg shadow-black/30">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-center">
        <div className="flex flex-1 items-start gap-4">
          <MarketArtwork
            src={coverImage}
            alt={`Artwork for ${market.title}`}
            sizeClass="w-24 h-24 sm:w-28 sm:h-28"
            roundedClass="rounded-2xl"
            borderClass="border border-white/15"
          />
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.3em] text-slate-400">
              <span className="rounded-full bg-white/10 px-2.5 py-1 text-white/80">{market.category ?? "Market"}</span>
              <span className="rounded-full border border-emerald-400/40 px-2.5 py-1 text-emerald-200">
                {market.status ?? "Active"}
              </span>
              <span className="rounded-full border border-white/15 px-2.5 py-1 text-white/70">
                ZEN in / USDC profit
              </span>
              <span className="rounded-full border border-sky-400/50 px-2.5 py-1 text-sky-200">
                Live prices streaming
              </span>
            </div>
            <h1 className="text-2xl font-semibold leading-snug text-white md:text-3xl">{market.title}</h1>
            <p className="text-sm leading-6 text-slate-400">
              Last updated {market.updatedAt ? formatDateTime(market.updatedAt) : "recently"} ·{" "}
              {market.resolutionSource ?? "Resolution mirrored from backend ledger"}
            </p>
          </div>
        </div>
        <div className="grid gap-3 rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-4 text-sm text-slate-300 md:min-w-[280px] md:px-6">
          <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.3em] text-slate-500">
            <span>Commit close</span>
            <span className="text-base font-semibold text-white">
              {market.commitDeadline ? formatDate(market.commitDeadline) : "TBA"}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.3em] text-slate-500">
            <span>Reveal close</span>
            <span className="text-base font-semibold text-white">
              {market.revealDeadline ? formatDate(market.revealDeadline) : "TBA"}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.3em] text-slate-500">
            <span>Yes price</span>
            <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-semibold text-emerald-200">
              {yesProbability !== null ? `${yesProbability}% (${formatZenPrice(yesPrice)})` : "—"}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.3em] text-slate-500">
            <span>No price</span>
            <span className="rounded-full bg-rose-500/15 px-3 py-1 text-xs font-semibold text-rose-200">
              {noProbability !== null ? `${noProbability}% (${formatZenPrice(noPrice)})` : "—"}
            </span>
          </div>
        </div>
      </div>
      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:max-w-xl">
        <Link
          href={{ pathname: "/markets/[eventId]", query: { eventId: market.eventId, outcome: "0" } }}
          className="flex min-h-[56px] w-full items-center justify-center gap-3 rounded-xl bg-emerald-500 px-6 py-3 text-base font-semibold text-slate-950 shadow-lg shadow-emerald-500/40 transition hover:-translate-y-0.5 hover:bg-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-200"
        >
          <span>Buy YES</span>
          <span className="rounded-full bg-emerald-900/70 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-emerald-100">
            {yesLabel}
          </span>
        </Link>
        <Link
          href={{ pathname: "/markets/[eventId]", query: { eventId: market.eventId, outcome: "1" } }}
          className="flex min-h-[56px] w-full items-center justify-center gap-3 rounded-xl bg-rose-500 px-6 py-3 text-base font-semibold text-white shadow-lg shadow-rose-500/40 transition hover:-translate-y-0.5 hover:bg-rose-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-200"
        >
          <span>Buy NO</span>
          <span className="rounded-full bg-rose-900/70 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-rose-100">
            {noLabel}
          </span>
        </Link>
      </div>
    </header>
  );
}
