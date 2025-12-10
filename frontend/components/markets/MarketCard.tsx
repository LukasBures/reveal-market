import type { MarketSummary } from "@/lib/api-types";
import type { Route } from "next";
import Link from "next/link";
import { MarketArtwork } from "./MarketArtwork";
import { getMarketVolume } from "@/lib/markets";

type Props = {
  market: MarketSummary;
};

const FALLBACK_COLORS: Record<string, string> = {
  politics: "#1d2c9f",
  sports: "#0c1346",
  finance: "#2a3ed1",
  crypto: "#3b5cff",
  geopolitics: "#6a8bff",
  "ai & tech": "#0f172a",
  trending: "#4c1d95",
};

const buildPlaceholderDataUrl = (label: string) => {
  const base = label.trim().charAt(0).toUpperCase() || "?";
  const background = FALLBACK_COLORS[label.toLowerCase()] ?? "#0f172a";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" rx="12" fill="${background}"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="Manrope, Arial" font-size="28" fill="#ffffff">${base}</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
};

const normalizeProbability = (value?: number | null): number | undefined => {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return undefined;
  }
  return Math.min(1, Math.max(0, value));
};

const formatProbability = (value?: number | null) =>
  value === undefined || value === null ? "—" : `${Math.round((value ?? 0) * 100)}%`;

const formatStatValue = (value?: number | null) =>
  value === undefined || value === null ? "—" : `$${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Math.max(0, value))}`;

export function MarketCard({ market }: Props) {
  const outcomes = market.outcomes ?? [];
  const visibleOutcomes = outcomes.length > 0 ? outcomes.slice(0, 2) : ["Awaiting outcomes"];
  const categoryLabel = market.category ?? "General";
  const volumeUsd = getMarketVolume(market);
  const extraImage =
    market.extraData && typeof market.extraData === "object"
      ? (market.extraData as Record<string, any>).image_url ??
        (market.extraData as Record<string, any>).imageUrl ??
        (market.extraData as Record<string, any>).gamma?.image_url ??
        (market.extraData as Record<string, any>).gamma?.imageUrl ??
        (market.extraData as Record<string, any>).gamma?.cover_image ??
        (market.extraData as Record<string, any>).gamma?.coverImage
      : null;
  const coverImage = market.imageUrl ?? extraImage ?? buildPlaceholderDataUrl(categoryLabel);
  const targetHref = (market.groupSlug
    ? `/markets/group/${encodeURIComponent(market.groupSlug)}`
    : `/markets/${encodeURIComponent(market.eventId)}`) as Route;
  const isBinary = outcomes.length === 2;
  let primaryProbabilityValue = normalizeProbability(market.outcomePrices?.[0]);
  let secondaryProbabilityValue = normalizeProbability(market.outcomePrices?.[1]);
  if (primaryProbabilityValue === undefined && secondaryProbabilityValue !== undefined) {
    primaryProbabilityValue = Math.max(0, Math.min(1, 1 - secondaryProbabilityValue));
  }
  if (secondaryProbabilityValue === undefined && primaryProbabilityValue !== undefined) {
    secondaryProbabilityValue = Math.max(0, Math.min(1, 1 - primaryProbabilityValue));
  }
  const primaryProbability = formatProbability(primaryProbabilityValue);
  const secondaryProbability = formatProbability(secondaryProbabilityValue);

  return (
    <Link
      href={targetHref}
      prefetch
      className="group relative flex h-full flex-col gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-4 shadow-[0_25px_60px_rgba(1,3,20,0.65)] transition duration-200 hover:-translate-y-1.5 hover:border-brand-400/60 hover:bg-white/10"
    >
      <div className="pointer-events-none absolute -top-12 right-0 h-40 w-40 rounded-full bg-gradient-to-b from-white/10 to-transparent opacity-80 blur-3xl transition duration-200 group-hover:opacity-100" />
      <div className="pointer-events-none absolute inset-0 border border-white/5 opacity-0 transition duration-200 group-hover:opacity-70" />
      <div className="flex flex-1 flex-col gap-3">
        <div className="flex items-start gap-4">
          <MarketArtwork src={coverImage} alt={`Artwork for ${market.title}`} />
          <div>
            <h3 className="mt-1 text-base font-semibold text-white line-clamp-2 sm:text-lg">{market.title}</h3>
          </div>
        </div>
        {isBinary ? (
          <>
            <div className="mt-1 min-h-[86px] space-y-1 text-xs text-slate-300">
              {outcomes.map((outcome, idx) => {
                const hoverColor =
                  idx === 0
                    ? "transition hover:bg-emerald-500/20"
                    : idx === 1
                      ? "transition hover:bg-rose-500/25"
                      : "transition hover:bg-white/10";
                const probability = idx === 0 ? primaryProbability : secondaryProbability;
                return (
                  <div
                    key={outcome}
                    className={`flex items-center justify-between rounded-lg bg-slate-900/60 px-3 py-1.5 ${hoverColor}`}
                  >
                    <span className="truncate">{outcome}</span>
                    <span className="font-semibold text-white">{probability}</span>
                  </div>
                );
              })}
            </div>
            <div className="mt-auto grid grid-cols-2 gap-2 text-[11px] uppercase tracking-[0.25em] text-white/60">
              <div className="flex items-center justify-between rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2">
                <span>24h vol</span>
                <span className="font-semibold text-white/80">{formatStatValue(volumeUsd)}</span>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2">
                <span>Liquidity</span>
                <span className="font-semibold text-white/80">{formatStatValue(market.liquidityUsd)}</span>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="mt-1 min-h-[86px] space-y-1 text-xs text-slate-300">
              {visibleOutcomes.map((outcome, idx) => {
                const probability = formatProbability(normalizeProbability(market.outcomePrices?.[idx]));
                const hoverColor =
                  idx === 0
                    ? "transition hover:bg-emerald-900/40"
                    : idx === 1
                      ? "transition hover:bg-rose-900/40"
                      : "transition hover:bg-white/10";
                return (
                  <div
                    key={outcome}
                    className={`flex items-center justify-between rounded-lg bg-slate-900 px-3 py-1.5 ${hoverColor}`}
                  >
                    <span className="truncate">{outcome}</span>
                    <span className="font-semibold text-white">{probability}</span>
                  </div>
                );
              })}
            </div>
            <div className="mt-auto grid grid-cols-2 gap-2 text-[11px] uppercase tracking-[0.25em] text-white/60">
              <div className="flex items-center justify-between rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2">
                <span>24h vol</span>
                <span className="font-semibold text-white/80">{formatStatValue(volumeUsd)}</span>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2">
                <span>Liquidity</span>
                <span className="font-semibold text-white/80">{formatStatValue(market.liquidityUsd)}</span>
              </div>
            </div>
          </>
        )}
      </div>
    </Link>
  );
}
