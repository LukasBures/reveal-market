 "use client";

import type { MarketDetail } from "@/lib/api";

type Props = {
  market: MarketDetail;
};

type MetadataItem = {
  label: string;
  value?: string | null;
  mono?: boolean;
};

export function MarketDetailMetadata({ market }: Props) {
  const items: MetadataItem[] = [
    { label: "Condition ID", value: market.conditionId, mono: true },
    { label: "Question ID", value: market.questionId, mono: true },
    { label: "UMA status", value: market.umaStatus ?? "pending" },
    { label: "Market address", value: market.marketAddress, mono: true },
    { label: "Event ID", value: market.eventId },
  ];
  const tags = market.tags ?? [];
  type ResolutionWinner = { index: number; label?: string | null; payout?: number | null };
  const resolution = (market.resolution ?? (market.extraData?.resolution as any)) || null;
  const resolutionWinners: ResolutionWinner[] = Array.isArray(resolution?.winners)
    ? (resolution.winners as ResolutionWinner[])
    : [];
  const heartbeat = market.heartbeat ?? (market.extraData?.heartbeat as any);

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
            Mirror of an UMA-backed feed with immutable IDs for downstream systems.
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
                <span className="text-xs text-slate-500">
                  {new Date(resolution.checkedAt).toLocaleString()}
                </span>
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
            {market.commitDeadline ? new Date(market.commitDeadline).toLocaleString() : "TBA"}
          </p>
        </div>
        <div className="rounded-3xl border border-white/10 bg-slate-900/40 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Reveal deadline</p>
          <p className="mt-2 text-lg font-semibold text-white">
            {market.revealDeadline ? new Date(market.revealDeadline).toLocaleString() : "TBA"}
          </p>
        </div>
      </div>
      {heartbeat && (
        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-900/40 p-6 text-sm text-slate-300">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Data freshness</p>
          <p className="mt-2">
            Last worker sync at{" "}
            <span className="text-white">
              {heartbeat.timestamp ? new Date(heartbeat.timestamp).toLocaleString() : "unknown"}
            </span>
            {typeof heartbeat.latencyMs === "number" && (
              <>
                {" "}
                <span className="text-slate-400">(latency {Math.round(heartbeat.latencyMs)} ms)</span>
              </>
            )}
          </p>
          {typeof heartbeat.marketsProcessed === "number" && (
            <p className="text-xs text-slate-500">
              Markets processed in last batch: {heartbeat.marketsProcessed}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
