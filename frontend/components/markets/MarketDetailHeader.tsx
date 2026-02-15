import type { MarketDetail } from "@/lib/api-types";
import { formatDateTime, formatUsd, formatUsdCompact } from "@/lib/formatters";
import { getCommitDeadline } from "@/lib/markets";
import Image from "next/image";
import { MarketArtwork } from "./MarketArtwork";

type Props = {
  market: MarketDetail;
  coverImage?: string;
};

export function MarketDetailHeader({ market, coverImage }: Props) {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const gamma = (extraData?.gamma || {}) as Record<string, any>;
  const toNumber = (value: unknown): number | null => {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
      const parsed = Number(value.replace(/,/g, ""));
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  };
  const liquidity =
    toNumber(market.liquidityUsd) ??
    toNumber(market.liquidityUsd) ??
    toNumber(extraData?.liquidity_usd) ??
    toNumber(extraData?.liquidityUsd) ??
    toNumber(gamma?.liquidity) ??
    0;
  const volume24h =
    toNumber(market.volume24hUsd) ??
    toNumber(market.orderbookVolumeUsd) ??
    toNumber(extraData?.volume24h) ??
    toNumber(extraData?.volume_24h) ??
    toNumber(gamma?.volume24h) ??
    toNumber(gamma?.volume24H) ??
    0;
  const openInterest =
    toNumber(market.openInterestUsd) ?? toNumber(extraData?.openInterest) ?? toNumber(gamma?.openInterest) ?? 0;
  const commitDeadline = getCommitDeadline(market);
  const resolutionStatus = (market.resolutionStatus ?? "").toLowerCase();
  const resolutionReason = market.resolutionReason ?? null;
  return (
    <header
      className="relative overflow-hidden rounded-3xl border border-slate-800 bg-slate-950 px-5 py-6 shadow-[0_20px_60px_rgba(0,0,0,0.35)] sm:px-8 sm:py-8"
    >
      {coverImage ? (
        <>
          <Image
            src={coverImage}
            alt=""
            fill
            priority
            sizes="(max-width: 1024px) 100vw, 1024px"
            className="pointer-events-none absolute inset-0 z-0 object-cover"
          />
          <div className="pointer-events-none absolute inset-0 z-10 bg-gradient-to-br from-slate-950/95 via-slate-950/75 to-black/60" />
        </>
      ) : null}
      <div className="relative z-20">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-8">
        <div className="flex min-w-0 flex-1 gap-4">
          <MarketArtwork src={coverImage} alt={`Artwork for ${market.title}`} sizeClass="w-20 h-20 sm:w-24 sm:h-24" />
          <div className="min-w-0 space-y-3">
            <h1 className="break-words text-2xl font-semibold text-white sm:text-3xl">
              {market.groupTitle || market.groupSlug || market.title}
            </h1>
            {market.status && (
              <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-slate-400">
                {market.category && (
                  <span className="rounded-full bg-white/5 px-3 py-1 text-white/80">{market.category}</span>
                )}
                <span className="rounded-full bg-brand-500/20 px-2.5 py-1 text-brand-100">
                  {market.status}
                </span>
                {resolutionStatus === "pending_resolution" && (
                  <span className="rounded-full bg-amber-500/20 px-3 py-1 text-amber-100">Waiting for resolution</span>
                )}
                {resolutionStatus === "disputed" && (
                  <span className="rounded-full bg-rose-500/20 px-3 py-1 text-rose-100">
                    Disputed{resolutionReason ? `: ${resolutionReason}` : ""}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Liquidity" value={formatUsd(liquidity)} />
        <Stat label="24h volume" value={formatUsd(volume24h)} />
        <Stat label="Open interest" value={formatUsdCompact(openInterest)} />
        <Stat
          label="Commit deadline"
          value={commitDeadline ? formatDateTime(commitDeadline) : "TBA"}
          compact
        />
      </div>
      </div>
    </header>
  );
}

function Stat({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
      <p className="text-[11px] uppercase tracking-[0.3em] text-slate-400">{label}</p>
      <p className={`mt-1 font-semibold text-white ${compact ? "text-sm" : "text-lg"}`}>{value}</p>
    </div>
  );
}
