import type { EventSummary } from "@/lib/api-types";
import type { Route } from "next";
import { MarketArtwork } from "@/components/markets/MarketArtwork";
import { formatUsdCompact } from "@/lib/formatters";
import { EventCardLink } from "@/components/events/EventCardLink";

type Props = {
  event: EventSummary;
  priority?: boolean;
};

const buildHref = (event: EventSummary) => {
  return `/events/${encodeURIComponent(event.eventId)}` as Route;
};

const formatProbability = (value?: number | null) =>
  value === undefined || value === null ? "—" : `${Math.round(value * 100)}%`;

const formatStatValue = (value?: number | null) => formatUsdCompact(value, { maximumFractionDigits: 1 });

export function EventCardMultiOutcome({ event, priority = false }: Props) {
  const markets = event.markets ?? [];
  const coverImage = event.imageUrl ?? markets[0]?.imageUrl ?? null;
  const isPriority = priority;
  const href = buildHref(event);
  const preview = markets.slice(0, 3);

  return (
    <div className="group relative flex h-auto cursor-pointer flex-col gap-3 overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-3 shadow-[0_25px_60px_rgba(1,3,20,0.65)] transition duration-200 will-change-transform [backface-visibility:hidden] [transform:translateZ(0)] hover:-translate-y-1.5 hover:border-brand-400/60 hover:bg-white/10 sm:h-[256px]">
      <div className="pointer-events-none absolute -top-12 right-0 h-40 w-40 rounded-full bg-gradient-to-b from-white/10 to-transparent opacity-80 blur-3xl transition duration-200 group-hover:opacity-100" />
      <div className="pointer-events-none absolute inset-0 border border-white/5 opacity-0 transition duration-200 group-hover:opacity-70" />
      <EventCardLink
        href={href}
        prefetchOnView
        aria-label={`Open ${event.title}`}
        className="absolute inset-0 z-10 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
      />
      <div className="pointer-events-none relative z-20 flex items-start gap-3">
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
          <p className="mt-1 text-xs uppercase tracking-[0.25em] text-white/60">{markets.length} markets</p>
        </div>
      </div>
      <div className="pointer-events-none relative z-20 mt-2 space-y-2">
        {preview.map((market) => (
          <div key={market.eventId} className="flex items-center justify-between text-sm text-white/80">
            <span className="truncate">{market.groupItemTitle ?? market.title}</span>
            <span className="font-semibold text-white">{formatProbability(market.outcomePrices?.[0])}</span>
          </div>
        ))}
      </div>
      <div className="pointer-events-none relative z-20 mt-auto flex items-center justify-between text-xs text-white/60">
        <span>Volume</span>
        <span className="font-semibold text-white/80">
          {formatStatValue(event.aggregateVolumeTotalUsd ?? event.aggregateVolume24hUsd)}
        </span>
      </div>
    </div>
  );
}
