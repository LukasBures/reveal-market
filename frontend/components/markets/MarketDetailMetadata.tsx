"use client";

import type { MarketDetail } from "@/lib/api-types";
import { formatDateTime } from "@/lib/formatters";

type Props = {
  market: MarketDetail;
};

type MetadataItem = {
  label: string;
  value?: string | null;
  mono?: boolean;
};

export function MarketDetailMetadata({ market }: Props) {
  const extraData = (market.extraData && typeof market.extraData === "object" ? market.extraData : null) as
    | Record<string, any>
    | null;
  const gamma = extraData?.gamma as Record<string, any> | undefined;
  const sourceSlug =
    typeof gamma?.slug === "string" && gamma.slug.trim()
      ? gamma.slug
      : typeof market.slug === "string"
        ? market.slug
        : undefined;
  const clobPairId =
    typeof gamma?.clobPairId === "string"
      ? gamma.clobPairId
      : typeof gamma?.pairId === "string"
        ? gamma.pairId
        : undefined;
  const tokenIds = Array.isArray(gamma?.clobTokenIds ?? gamma?.tokenIds)
    ? (gamma?.clobTokenIds ?? gamma?.tokenIds).map((value: any) => String(value))
    : undefined;
  const formattedTokens = tokenIds?.length ? tokenIds.join(", ") : undefined;
  const feeLabel =
    typeof market.rakeBps === "number" && Number.isFinite(market.rakeBps)
      ? `${Math.round(market.rakeBps)} bps`
      : undefined;

  const items: MetadataItem[] = [
    { label: "UMA status", value: market.umaStatus ?? "pending" },
    { label: "Market address", value: market.marketAddress, mono: true },
    { label: "Event ID", value: market.eventId },
  ];
  if (market.factory) {
    items.push({ label: "Factory address", value: market.factory, mono: true });
  }
  if (sourceSlug) {
    items.push({ label: "Source slug", value: sourceSlug, mono: true });
  }
  if (clobPairId) {
    items.push({ label: "CLOB pair ID", value: clobPairId, mono: true });
  }
  if (formattedTokens) {
    items.push({ label: "Order book tokens", value: formattedTokens, mono: true });
  }
  if (feeLabel) {
    items.push({ label: "Fee (bps)", value: feeLabel });
  }
  const tags = market.tags ?? [];
  type ResolutionWinner = { index: number; label?: string | null; payout?: number | null };
  const resolution = (market.resolution ?? (market.extraData?.resolution as any)) || null;
  const resolutionWinners: ResolutionWinner[] = Array.isArray(resolution?.winners)
    ? (resolution.winners as ResolutionWinner[])
    : [];

  const copyToClipboard = async (value?: string | null) => {
    if (!value || typeof navigator === "undefined" || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch (error) {
      console.error("Unable to copy value", error);
    }
  };

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 text-sm text-slate-300">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Prediction metadata</p>
          <h2 className="text-2xl font-semibold text-white">Identifiers & provenance</h2>
          <p className="text-slate-400">
            Backed by the Reveal Market ledger with immutable IDs, so downstream systems can reconcile settlements and audits without chasing upstream quirks.
          </p>
        </div>
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {items.map((item) => (
          <div
            key={item.label}
            className="rounded-2xl border border-white/10 bg-slate-900/60 px-4 py-3 text-sm text-slate-200"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">{item.label}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className={`${item.mono ? "font-mono text-xs" : "text-base font-semibold text-white"}`}>
                {item.value ?? "—"}
              </span>
              {item.value && (
                <button
                  type="button"
                  onClick={() => copyToClipboard(item.value)}
                  className="text-xs uppercase tracking-[0.2em] text-slate-400 transition hover:text-brand-200"
                  aria-label={`Copy ${item.label}`}
                >
                  Copy
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {tags.length > 0 && (
        <div className="mt-6 space-y-2">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Tags</p>
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <span key={tag} className="rounded-full bg-brand-500/15 px-3 py-1 text-xs font-semibold text-brand-200">
                #{tag}
              </span>
            ))}
          </div>
        </div>
      )}
      {resolution && (
        <div className="mt-6 space-y-3 rounded-3xl border border-white/10 bg-slate-900/40 p-6">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Resolution</p>
          <div className="text-sm text-slate-300">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-white">{resolution.resolved ? "Resolved" : "Pending"}</span>
              {resolution.checkedAt && (
                <span className="text-xs text-slate-500">{formatDateTime(resolution.checkedAt)}</span>
              )}
            </div>
            {resolutionWinners.length > 0 && (
              <ul className="mt-2 space-y-1 text-sm">
                {resolutionWinners.map((winner: ResolutionWinner) => (
                  <li key={`${winner.index}-${winner.label ?? winner.index}`}>
                    <span className="font-semibold text-white">{winner.label ?? `Outcome ${winner.index}`}</span>
                    <span className="text-slate-400">
                      {" "}
                      — payout {typeof winner.payout === "number" ? `${Math.round(winner.payout * 100)}%` : "pending"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
      <div className="mt-6 grid gap-4 md:grid-cols-2 text-sm text-slate-300">
        <div className="rounded-3xl border border-white/10 bg-slate-900/40 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Commit deadline</p>
          <p className="mt-2 text-lg font-semibold text-white">
            {market.commitDeadline ? formatDateTime(market.commitDeadline) : "TBA"}
          </p>
        </div>
        <div className="rounded-3xl border border-white/10 bg-slate-900/40 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Reveal deadline</p>
          <p className="mt-2 text-lg font-semibold text-white">
            {market.revealDeadline ? formatDateTime(market.revealDeadline) : "TBA"}
          </p>
        </div>
      </div>
    </section>
  );
}
