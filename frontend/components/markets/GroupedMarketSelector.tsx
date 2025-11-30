import Link from "next/link";
import type { MarketSibling } from "@/lib/api-types";
import { formatUsd } from "@/lib/formatters";

type Props = {
  groupSlug: string;
  siblings: MarketSibling[];
  activeEventId: string;
};

const formatGroupTitle = (slug: string): string =>
  slug
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

const formatPrice = (value: number | null | undefined): string => {
  if (typeof value === "number" && Number.isFinite(value)) return `$${value.toFixed(3)}`;
  return "—";
};

export function GroupedMarketSelector({ groupSlug, siblings, activeEventId }: Props) {
  if (!groupSlug || siblings.length <= 1) return null;
  const title = formatGroupTitle(groupSlug);

  return (
    <section className="rounded-3xl border border-emerald-900/60 bg-emerald-900/20 px-5 py-5 shadow-inner shadow-emerald-500/10 sm:px-7 sm:py-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.3em] text-emerald-200/70">Grouped market</p>
          <h2 className="text-xl font-semibold text-white">{title}</h2>
          <p className="text-sm text-emerald-100/80">Select a threshold to jump between sub-markets.</p>
        </div>
        <span className="rounded-full border border-emerald-700 bg-emerald-500/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] text-emerald-50">
          {siblings.length} sub-markets
        </span>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {siblings.map((sibling) => {
          const active = sibling.eventId === activeEventId;
          const label = sibling.groupItemTitle || sibling.title || sibling.eventId;
          return (
            <Link
              key={sibling.eventId}
              href={`/markets/${encodeURIComponent(sibling.eventId)}`}
              className={`rounded-full border px-4 py-2 text-sm font-semibold transition ${
                active
                  ? "border-emerald-400 bg-emerald-500/20 text-white shadow-md shadow-emerald-500/20"
                  : "border-white/10 bg-white/5 text-white/80 hover:border-emerald-400/60 hover:text-white"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {siblings.map((sibling) => {
          const yesPrice = formatPrice(sibling.outcomePrices?.[0] ?? null);
          const noPrice = formatPrice(sibling.outcomePrices?.[1] ?? null);
          const volume = sibling.volume24hUsd ?? null;
          return (
            <div
              key={`${sibling.eventId}-summary`}
              className={`rounded-2xl border px-4 py-3 transition ${
                sibling.eventId === activeEventId ? "border-emerald-400 bg-emerald-500/10" : "border-white/5 bg-white/5"
              }`}
            >
              <p className="text-[11px] uppercase tracking-[0.25em] text-emerald-100/70">
                {sibling.groupItemTitle || sibling.title || "Sub-market"}
              </p>
              <div className="mt-2 flex items-center justify-between text-sm text-white">
                <span>Yes {yesPrice}</span>
                <span>No {noPrice}</span>
              </div>
              <p className="mt-1 text-xs text-emerald-100/80">24h vol {formatUsd(volume ?? 0)}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
