import type { MarketDetail } from "@/lib/api-types";
import { formatDateTime, formatUsd } from "@/lib/formatters";
import { MarketArtwork } from "./MarketArtwork";
import { LiveFxBadge } from "./LiveFxBadge";

type Props = {
  market: MarketDetail;
  coverImage?: string;
};

export function MarketDetailHeader({ market, coverImage }: Props) {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const prices = Array.isArray(market.outcomePrices) ? market.outcomePrices : [];
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
    toNumber(extraData?.liquidity_usd) ??
    toNumber(extraData?.liquidityUsd) ??
    toNumber(gamma?.liquidity);
  const volume24h = toNumber(extraData?.volume24h) ?? toNumber(gamma?.volume24h) ?? toNumber(gamma?.volume24H);
  const openInterest = toNumber(extraData?.openInterest) ?? toNumber(gamma?.openInterest);
  const backgroundStyle = coverImage
    ? {
        backgroundImage: `linear-gradient(120deg, rgba(15,23,42,0.9) 0%, rgba(15,23,42,0.75) 45%, rgba(0,0,0,0.6) 100%), url(${coverImage})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }
    : undefined;

  return (
    <header
      className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-950 px-5 py-6 shadow-[0_20px_60px_rgba(0,0,0,0.35)] sm:px-8 sm:py-8"
      style={backgroundStyle}
    >
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
            {Array.isArray(market.outcomes) && market.outcomes.length > 0 && (
              <div className="flex flex-wrap gap-2 text-sm text-white/90">
                {market.outcomes.slice(0, 2).map((label, idx) => {
                  const price = Number(prices[idx] ?? 0);
                  const pct = Number.isFinite(price) ? Math.round(price * 100) : null;
                  return (
                    <a
                      key={`${market.eventId}-cta-${idx}`}
                      href={`#buy-${idx}`}
                      className="rounded-full bg-white/15 px-3 py-1 text-white transition hover:bg-white/25"
                      aria-label={`Buy ${label ?? `Outcome ${idx + 1}`}`}
                    >
                      Buy {label ?? `Outcome ${idx + 1}`} {pct !== null ? `· ${pct}%` : ""}
                    </a>
                  );
                })}
              </div>
            )}
            <LiveFxBadge />
          </div>
        </div>
      </div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Liquidity" value={formatUsd(liquidity)} />
        <Stat label="24h volume" value={formatUsd(volume24h)} />
        <Stat label="Open interest" value={formatUsd(openInterest)} />
        <Stat
          label="Commit deadline"
          value={market.commitDeadline ? formatDateTime(market.commitDeadline) : "TBA"}
          compact
        />
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
