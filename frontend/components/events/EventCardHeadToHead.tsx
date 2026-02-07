import type { EventSummary, MarketSummary } from "@/lib/api-types";
import type { Route } from "next";
import Link from "next/link";
import { MarketArtwork } from "@/components/markets/MarketArtwork";
import { formatUsdCompact } from "@/lib/formatters";

type Props = {
  event: EventSummary;
  market?: MarketSummary;
};

const buildHref = (event: EventSummary) => {
  const key = event.groupSlug || event.eventId;
  return `/events/${encodeURIComponent(key)}` as Route;
};

const formatProbability = (value?: number | null) =>
  value === undefined || value === null ? "—" : `${Math.round(value * 100)}%`;

const formatStatValue = (value?: number | null) => formatUsdCompact(value, { maximumFractionDigits: 1 });

export function EventCardHeadToHead({ event, market }: Props) {
  const outcomes = (market?.outcomes ?? []).slice(0, 3);
  const odds = market?.outcomePrices ?? [];
  const coverImage = event.imageUrl ?? market?.imageUrl ?? null;
  const isPriority = event.eventId?.endsWith("-p") === true;
  const href = buildHref(event);
  if (outcomes.length < 2) {
    return null;
  }
  const buttonOutcomes = outcomes.slice(0, 3);
  const gridColsClass = buttonOutcomes.length === 3 ? "grid-cols-3" : "grid-cols-2";

  return (
    <div className="group relative flex h-full flex-col gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-3 shadow-[0_25px_60px_rgba(1,3,20,0.65)] transition duration-200 hover:-translate-y-1.5 hover:border-brand-400/60 hover:bg-white/10">
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
        </div>
      </Link>
      <div className="mt-2 space-y-2">
        {outcomes.slice(0, 3).map((label, idx) => (
          <div key={label} className="flex items-center justify-between text-sm text-white/80">
            <span className="truncate">{label}</span>
            <span className="font-semibold text-white">{formatProbability(odds[idx])}</span>
          </div>
        ))}
      </div>
      <div className={`mt-auto grid ${gridColsClass} gap-2`}>
        {buttonOutcomes.map((label, idx) => {
          const isThreeWay = buttonOutcomes.length === 3;
          const isLeft = idx === 0;
          const isMiddle = isThreeWay && idx === 1;
          const isRight = isThreeWay ? idx === 2 : idx === 1;
          const toneClass = isMiddle
            ? "border-white/10 bg-white/5 text-white/80 hover:bg-white/10"
            : isLeft
              ? "border-sky-400/30 bg-sky-500/10 text-sky-100 hover:bg-sky-500/20"
              : "border-amber-300/30 bg-amber-400/10 text-amber-100 hover:bg-amber-400/20";
          return (
          <a
            key={label}
            href={`${href}?outcome=${idx}#trade-panel`}
            className={`min-w-0 rounded-lg border px-3 py-2 text-sm font-semibold transition ${toneClass}`}
          >
            <span className="block truncate">{label}</span>
          </a>
        );
        })}
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-white/60">
        <span>Volume</span>
        <span className="font-semibold text-white/80">{formatStatValue(event.aggregateVolume24hUsd)}</span>
      </div>
    </div>
  );
}
