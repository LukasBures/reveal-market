"use client";

import type { MarketDetail } from "@/lib/api-types";
import { formatDateTime, formatNumber, formatUsdCompact } from "@/lib/formatters";
import { getCommitDeadline } from "@/lib/markets";

type Props = {
  market: MarketDetail;
};

const formatCount = (value?: number | null) => {
  if (value === null || value === undefined) return "—";
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
};

const StatPill = ({ label, value }: { label: string; value: string }) => (
  <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/60 px-3 py-1 text-[11px] uppercase tracking-[0.25em] text-slate-300">
    <span className="text-slate-500">{label}</span>
    <span className="text-white">{value}</span>
  </span>
);

export function MarketInfoCompact({ market }: Props) {
  const commitDeadline = getCommitDeadline(market);
  const resolverSource =
    market.resolutionSource ??
    (market.extraData as any)?.resolution_source ??
    (market.extraData as any)?.gamma?.resolution_source ??
    null;
  const resolverLabel = typeof resolverSource === "string" && resolverSource.trim() ? resolverSource.trim() : "Not set";

  const tradesCount =
    typeof market.tradesQuantity === "number" && Number.isFinite(market.tradesQuantity) ? market.tradesQuantity : null;
  const volumeBase =
    typeof market.volume === "number" && Number.isFinite(market.volume)
      ? market.volume
      : typeof market.orderbookVolumeUsd === "number" && Number.isFinite(market.orderbookVolumeUsd)
        ? market.orderbookVolumeUsd
        : typeof market.volume24hUsd === "number" && Number.isFinite(market.volume24hUsd)
          ? market.volume24hUsd
          : null;
  const avgTrade =
    tradesCount && volumeBase !== null ? formatUsdCompact(volumeBase / tradesCount) : "—";

  return (
    <section className="rounded-2xl border border-white/10 bg-slate-950/40 p-4 text-xs text-slate-300">
      <p className="text-[11px] uppercase tracking-[0.35em] text-slate-500">Market info</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <StatPill label="24h vol" value={formatUsdCompact(market.volume24hUsd ?? market.orderbookVolumeUsd)} />
        <StatPill label="Liq" value={formatUsdCompact(market.liquidityUsd)} />
        <StatPill label="OI" value={formatUsdCompact(market.openInterestUsd)} />
        <StatPill label="Trades" value={formatCount(market.tradesQuantity)} />
        <StatPill label="Avg" value={avgTrade} />
        <StatPill label="UMA" value={market.umaStatus ?? "pending"} />
        <StatPill label="Commit" value={commitDeadline ? formatDateTime(commitDeadline) : "TBA"} />
        <StatPill label="Reveal" value={market.revealDeadline ? formatDateTime(market.revealDeadline) : "TBA"} />
        <StatPill label="Resolver" value={resolverLabel} />
        {market.marketAddress ? <StatPill label="Market" value={market.marketAddress} /> : null}
        {market.rakeBps ? <StatPill label="Rake" value={`${Math.round(market.rakeBps)} bps`} /> : null}
      </div>
    </section>
  );
}
