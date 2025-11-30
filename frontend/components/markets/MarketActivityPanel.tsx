import type { ActivityEntry } from "@/lib/streamer-data";

type Props = {
  activity: ActivityEntry[];
};

const typeLabel = {
  split: "Split",
  merge: "Merge",
  redemption: "Redemption",
};

const typeColor: Record<ActivityEntry["type"], string> = {
  split: "bg-sky-500/15 text-sky-100 border border-sky-400/20",
  merge: "bg-emerald-500/15 text-emerald-100 border border-emerald-400/20",
  redemption: "bg-amber-500/15 text-amber-100 border border-amber-400/20",
};

export function MarketActivityPanel({ activity }: Props) {
  if (!activity.length) {
    return (
      <section className="rounded-3xl border border-white/10 bg-slate-950/60 p-5 text-sm text-slate-400">
        <div className="flex items-center justify-between text-xs uppercase tracking-[0.25em] text-slate-500">
          <span>Activity</span>
          <span className="text-slate-400">Subgraph</span>
        </div>
        <p className="mt-3 text-slate-400">No recent splits/merges/redemptions.</p>
      </section>
    );
  }

  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/60 p-5">
      <div className="flex items-center justify-between text-xs uppercase tracking-[0.25em] text-slate-500">
        <span>Activity</span>
        <span className="text-slate-400">Subgraph</span>
      </div>
      <div className="mt-3 space-y-2">
        {activity.slice(0, 12).map((entry) => (
          <div
            key={entry.id}
            className="flex items-center justify-between rounded-2xl border border-white/5 bg-slate-900/70 px-3 py-2 text-sm text-slate-200"
          >
            <div className="flex items-center gap-2">
              <span className={`rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${typeColor[entry.type]}`}>
                {typeLabel[entry.type]}
              </span>
              <span className="text-white/80">
                {entry.account ? `${entry.account.slice(0, 6)}…${entry.account.slice(-4)}` : "Unknown account"}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-400">
              {entry.amount !== undefined && <span>Amt {Number(entry.amount).toFixed(2)}</span>}
              {entry.payout !== undefined && <span>Payout {Number(entry.payout).toFixed(2)}</span>}
              {entry.timestamp && (
                <span>{new Date(entry.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
