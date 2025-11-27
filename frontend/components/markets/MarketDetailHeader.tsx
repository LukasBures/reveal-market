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

  return (
    <header className="rounded-3xl border border-slate-800 bg-slate-950 px-5 py-6 shadow-[0_20px_60px_rgba(0,0,0,0.35)] sm:px-8 sm:py-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-8">
        <div className="flex flex-1 gap-4">
          <MarketArtwork src={coverImage} alt={`Artwork for ${market.title}`} sizeClass="w-20 h-20 sm:w-24 sm:h-24" />
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.3em] text-slate-400">
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
          </div>
        </div>
      </div>
    </header>
  );
}
