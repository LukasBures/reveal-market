import type { MarketSummary } from "@/lib/api-types";
import Link from "next/link";
import { MarketArtwork } from "./MarketArtwork";

type Props = {
  market: MarketSummary;
};

const currencyFormatter = Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });

function formatProbability(values?: number[]): string {
  if (!values || values.length === 0) return "—";
  const [yes] = values;
  return `${Math.round((yes ?? 0) * 100)}%`;
}

function formatLiquidity(value?: number | null): string {
  if (!value || Number.isNaN(value)) {
    return "—";
  }
  return currencyFormatter.format(value);
}

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

export function MarketCard({ market }: Props) {
  const yesProbability = formatProbability(market.outcomePrices);
  const outcomes = market.outcomes ?? [];
  const categoryLabel = market.category ?? "General";
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

  return (
    <Link
      href={`/markets/${market.eventId}`}
      className="group relative flex h-full flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 shadow-xl shadow-black/30 transition duration-200 hover:-translate-y-1 hover:border-brand-400/60 hover:bg-white/10"
    >
      <div className="flex items-center gap-4">
        <MarketArtwork src={coverImage} alt={`Artwork for ${market.title}`} />
        <div>
          <h3 className="mt-1 text-base font-semibold text-white sm:text-lg">{market.title}</h3>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{categoryLabel}</p>
        </div>
      </div>
      <div className="flex items-center justify-between rounded-xl bg-slate-950/60 px-3 py-2 text-sm">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Yes probability</p>
          <p className="text-2xl font-semibold text-white">{yesProbability}</p>
        </div>
      </div>
      {outcomes.length > 0 && (
        <div className="mt-1 space-y-1 text-xs text-slate-300">
          {outcomes.slice(0, 2).map((outcome, idx) => (
            <div key={outcome} className="flex items-center justify-between rounded-lg bg-slate-900/60 px-3 py-1.5">
              <span className="truncate">{outcome}</span>
              <span className="font-semibold text-white">
                {market.outcomePrices?.[idx]
                  ? `${Math.round((market.outcomePrices[idx] ?? 0) * 100)}%`
                  : idx === 0
                    ? yesProbability
                    : "—"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Link>
  );
}
