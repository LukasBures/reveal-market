import type { EventSummary, MarketSummary } from "@/lib/api-types";
import type { Route } from "next";
import Link from "next/link";
import { MarketArtwork } from "@/components/markets/MarketArtwork";
import { getMarketVolume } from "@/lib/markets";
import { formatUsdCompact } from "@/lib/formatters";

type Props = {
  event: EventSummary;
  market?: MarketSummary;
  priority?: boolean;
};

const buildHref = (event: EventSummary) => {
  return `/events/${encodeURIComponent(event.eventId)}` as Route;
};

const formatProbability = (value?: number | null) =>
  value === undefined || value === null ? "—" : `${Math.round(value * 100)}%`;

const formatStatValue = (value?: number | null) => formatUsdCompact(value, { maximumFractionDigits: 1 });

export function EventCardBinaryGauge({ event, market, priority = false }: Props) {
  const outcomes = (market?.outcomes ?? ["Yes", "No"]).slice(0, 2);
  const odds = market?.outcomePrices ?? [];
  if (outcomes.length < 2) {
    return null;
  }
  const chance = formatProbability(odds[0]);
  const volumeTotal = getMarketVolume(market ?? {}, "total");
  const coverImage = event.imageUrl ?? market?.imageUrl ?? null;
  const isPriority = priority;
  const href = buildHref(event);

  return (
    <div className="group relative flex h-auto flex-col gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-3 shadow-[0_25px_60px_rgba(1,3,20,0.65)] transition duration-200 will-change-transform [backface-visibility:hidden] [transform:translateZ(0)] hover:-translate-y-1.5 hover:border-brand-400/60 hover:bg-white/10 sm:h-[256px]">
      <div className="pointer-events-none absolute -top-12 right-0 h-40 w-40 rounded-full bg-gradient-to-b from-white/10 to-transparent opacity-80 blur-3xl transition duration-200 group-hover:opacity-100" />
      <div className="pointer-events-none absolute inset-0 border border-white/5 opacity-0 transition duration-200 group-hover:opacity-70" />
      <Link href={href} prefetch className="flex items-start gap-3">
        <MarketArtwork
          src={coverImage ?? undefined}
          alt={`Artwork for ${event.title}`}
          sizeClass="w-10 h-10"
          priority={isPriority}
        />
        <div className="min-w-0">
          <h3 className="min-h-[3rem] text-base font-semibold leading-snug text-white line-clamp-2 sm:text-lg">
            {event.title}
          </h3>
          <p className="mt-1 text-xs uppercase tracking-[0.25em] text-white/60">{chance} chance</p>
        </div>
      </Link>
      <div className="mt-auto grid grid-cols-2 gap-2">
        {outcomes.slice(0, 2).map((label, idx) => (
          <a
            key={label}
            href={`${href}?outcome=${idx}#trade-panel`}
            className={
              idx === 0
                ? "rounded-lg bg-emerald-500/15 px-3 py-2.5 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-500 hover:text-white sm:py-2"
                : "rounded-lg bg-rose-500/10 px-3 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500 hover:text-white sm:py-2"
            }
          >
            <span>{label}</span>
          </a>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-white/60">
        <span>Volume</span>
        <span className="font-semibold text-white/80">{formatStatValue(volumeTotal)}</span>
      </div>
    </div>
  );
}
