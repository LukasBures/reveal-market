export function MarketDetailChart() {
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/50 p-6">
      <div className="flex items-center justify-between text-sm text-slate-400">
        <span>Price history (synthetic)</span>
        <div className="flex gap-2 text-xs uppercase tracking-[0.2em]">
          {["1D", "1W", "1M", "ALL"].map((range, idx) => (
            <button
              key={range}
              className={`rounded-full px-3 py-1 ${
                idx === 3 ? "bg-brand-500 text-white" : "bg-white/5 text-slate-300"
              }`}
              type="button"
            >
              {range}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-4 h-60 rounded-2xl bg-gradient-to-b from-brand-500/30 via-slate-900/40 to-slate-950/80">
        <div className="h-full w-full bg-[radial-gradient(circle_at_30%_20%,rgba(99,102,241,0.3),transparent_60%),radial-gradient(circle_at_70%_50%,rgba(16,185,129,0.3),transparent_55%)]" />
      </div>
    </div>
  );
}
