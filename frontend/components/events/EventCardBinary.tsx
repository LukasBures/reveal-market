import type { EventSummary, MarketSummary } from "@/lib/api-types";
import type { Route } from "next";
import Link from "next/link";
import { MarketArtwork } from "@/components/markets/MarketArtwork";

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

const formatStatValue = (value?: number | null) =>
  value === undefined || value === null
    ? "—"
    : `$${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Math.max(0, value))}`;

export function EventCardBinary({ event, market }: Props) {
  const outcomes = market?.outcomes ?? [];
  const odds = market?.outcomePrices ?? [];
  const coverImage = event.imageUrl ?? market?.imageUrl ?? null;
  const href = buildHref(event);

  return (
    <div className="group relative flex h-full flex-col justify-between overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-4 shadow-[0_25px_60px_rgba(1,3,20,0.65)] transition duration-200 hover:-translate-y-1.5 hover:border-brand-400/60 hover:bg-white/10">
      <div className="pointer-events-none absolute -top-12 right-0 h-40 w-40 rounded-full bg-gradient-to-b from-white/10 to-transparent opacity-80 blur-3xl transition duration-200 group-hover:opacity-100" />
      <div className="pointer-events-none absolute inset-0 border border-white/5 opacity-0 transition duration-200 group-hover:opacity-70" />
      <Link href={href} prefetch className="flex items-start gap-3">
        <MarketArtwork src={coverImage ?? undefined} alt={`Artwork for ${event.title}`} sizeClass="w-10 h-10" />
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-white line-clamp-2 sm:text-lg">{event.title}</h3>
        </div>
      </Link>
      <div className="mt-3 space-y-2">
        {outcomes.slice(0, 2).map((label, idx) => (
          <div key={label} className="flex items-center justify-between text-sm text-white/80">
            <span className="truncate">{label}</span>
            <span className="font-semibold text-white">{formatProbability(odds[idx])}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        {outcomes.slice(0, 2).map((label, idx) => (
          <a
            key={label}
            href={`${href}?outcome=${idx}#trade-panel`}
            className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-semibold text-white/80 transition hover:bg-white/15 hover:text-white"
          >
            <span>{label}</span>
          </a>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-white/60">
        <span>Volume</span>
        <span className="font-semibold text-white/80">{formatStatValue(event.aggregateVolume24hUsd)}</span>
      </div>
    </div>
  );
}
