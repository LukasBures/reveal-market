import Link from "next/link";
import type { MarketDetail } from "@/lib/api-types";
import { formatDateTime, formatUsd } from "@/lib/formatters";
import { MarketArtwork } from "./MarketArtwork";

type Props = {
  market: MarketDetail;
  coverImage?: string;
};

export function MarketDetailHeader({ market, coverImage }: Props) {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const gamma = extraData?.gamma as Record<string, any> | undefined;
  const slug =
    typeof gamma?.slug === "string" && gamma.slug.trim()
      ? gamma.slug
      : typeof market.slug === "string"
        ? market.slug
        : null;

  const yesPrice = Array.isArray(market.outcomePrices) ? market.outcomePrices[0] : undefined;
  const noPrice = Array.isArray(market.outcomePrices) ? market.outcomePrices[1] : undefined;
  const yesLabel =
    typeof yesPrice === "number" && Number.isFinite(yesPrice)
      ? `${Math.round(yesPrice * 100)}% · ${yesPrice.toFixed(3)} ZEN`
      : "—";
  const noLabel =
    typeof noPrice === "number" && Number.isFinite(noPrice)
      ? `${Math.round(noPrice * 100)}% · ${noPrice.toFixed(3)} ZEN`
      : "—";
  const liquidity = formatUsd(market.liquidityUsd);
  const commitLabel = formatDateTime(market.commitDeadline) ?? "TBA";
  const revealLabel = formatDateTime(market.revealDeadline) ?? "TBA";

  return (
    <header className="rounded-3xl border border-slate-800 bg-slate-950 px-5 py-6 shadow-[0_20px_60px_rgba(0,0,0,0.35)] sm:px-8 sm:py-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-8">
        <div className="flex flex-1 gap-4">
          <MarketArtwork src={coverImage} alt={`Artwork for ${market.title}`} />
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.3em] text-slate-400">
              {slug && <span className="rounded-full bg-slate-800 px-2.5 py-1 text-white/80">{slug}</span>}
              {market.category && (
                <span className="rounded-full bg-slate-800 px-2.5 py-1 text-white/80">{market.category}</span>
              )}
              <span
                className={`rounded-full px-2.5 py-1 ${
                  market.status === "settled" || market.status === "resolved"
                    ? "bg-emerald-500/20 text-emerald-100"
                    : "bg-brand-500/20 text-brand-100"
                }`}
              >
                {market.status ?? "Active"}
              </span>
              {market.umaStatus && (
                <span className="rounded-full bg-slate-800 px-2.5 py-1 text-white/70">{market.umaStatus}</span>
              )}
            </div>
            <h1 className="text-2xl font-semibold text-white sm:text-3xl">{market.title}</h1>
            <p className="text-sm text-slate-400">
              Last updated {market.updatedAt ? formatDateTime(market.updatedAt) : "recently"}
            </p>
            <div className="flex flex-wrap gap-3">
              <Link
                href={`/markets/${market.eventId}?outcome=0`}
                className="inline-flex items-center justify-center rounded-full bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 shadow hover:bg-emerald-400 transition"
              >
                Buy YES
              </Link>
              <Link
                href={`/markets/${market.eventId}?outcome=1`}
                className="inline-flex items-center justify-center rounded-full bg-rose-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-rose-400 transition"
              >
                Buy NO
              </Link>
            </div>
          </div>
        </div>
        <div className="grid flex-1 gap-3 sm:grid-cols-2 lg:max-w-xl">
          <div className="rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Yes price</p>
            <p className="mt-2 text-lg font-semibold text-emerald-200">{yesLabel}</p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-500">No price</p>
            <p className="mt-2 text-lg font-semibold text-rose-200">{noLabel}</p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Liquidity</p>
            <p className="mt-2 text-lg font-semibold text-white">{liquidity}</p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Commit / Reveal</p>
            <p className="mt-2 text-sm text-slate-300">
              {commitLabel} • {revealLabel}
            </p>
          </div>
        </div>
      </div>
    </header>
  );
}
