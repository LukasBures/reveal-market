import type { EventSummary } from "@/lib/api-types";
import type { Route } from "next";
import Link from "next/link";
import { MarketArtwork } from "@/components/markets/MarketArtwork";

type Props = {
  event: EventSummary;
};

const buildHref = (event: EventSummary) => {
  const key = event.groupSlug || event.eventId;
  return `/events/${encodeURIComponent(key)}` as Route;
};

const formatProbability = (value?: number | null) =>
  value === undefined || value === null ? "—" : `${Math.round(value * 100)}%`;

const formatStatValue = (value?: number | null) =>
  value === undefined || value === null
    ? "—"
    : `$${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Math.max(0, value))}`;

export function EventCardMultiMarket({ event }: Props) {
  const markets = event.markets ?? [];
  const coverImage = event.imageUrl ?? markets[0]?.imageUrl ?? null;
  const href = buildHref(event);
  const preview = markets.slice(0, 4);

  return (
    <div className="group relative flex h-full flex-col justify-between overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-4 shadow-[0_25px_60px_rgba(1,3,20,0.65)] transition duration-200 hover:-translate-y-1.5 hover:border-brand-400/60 hover:bg-white/10">
      <div className="pointer-events-none absolute -top-12 right-0 h-40 w-40 rounded-full bg-gradient-to-b from-white/10 to-transparent opacity-80 blur-3xl transition duration-200 group-hover:opacity-100" />
      <div className="pointer-events-none absolute inset-0 border border-white/5 opacity-0 transition duration-200 group-hover:opacity-70" />
      <Link href={href} prefetch className="flex items-start gap-3">
        <MarketArtwork src={coverImage ?? undefined} alt={`Artwork for ${event.title}`} sizeClass="w-10 h-10" />
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-white line-clamp-2 sm:text-lg">{event.title}</h3>
          <p className="mt-1 text-xs uppercase tracking-[0.25em] text-white/60">{markets.length} markets</p>
        </div>
      </Link>
      <div className="mt-3 space-y-2">
        {preview.map((market) => (
          <div key={market.eventId} className="flex items-center justify-between text-sm text-white/80">
            <span className="truncate">{market.groupItemTitle ?? market.title}</span>
            <span className="font-semibold text-white">{formatProbability(market.outcomePrices?.[0])}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-white/60">
        <span>Volume</span>
        <span className="font-semibold text-white/80">{formatStatValue(event.aggregateVolume24hUsd)}</span>
      </div>
    </div>
  );
}
