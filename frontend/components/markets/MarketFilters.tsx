const categories = [
  "Trending",
  "Politics",
  "Sports",
  "Finance",
  "Crypto",
  "Geopolitics",
  "AI & Tech",
];

const quickTags = [
  "Gov shutdown",
  "Fed policy",
  "EU elections",
  "BTC halving",
  "AI regulation",
  "Climate",
];

export function MarketFilters() {
  return (
    <section className="space-y-6 rounded-3xl border border-white/5 bg-slate-900/60 p-6 shadow-lg shadow-black/40">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Explore</p>
          <h1 className="text-3xl font-semibold text-white">Live markets across every narrative.</h1>
        </div>
        <div className="relative w-full md:w-64">
          <input
            type="search"
            placeholder="Search markets"
            className="w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-white outline-none ring-brand-400/50 focus:ring-2"
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {categories.map((category) => (
          <button
            key={category}
            type="button"
            className="rounded-full border border-white/10 bg-slate-950/50 px-4 py-1 text-sm text-slate-200 transition hover:border-brand-400/60 hover:text-white"
          >
            {category}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {quickTags.map((tag) => (
          <span key={tag} className="rounded-full bg-brand-500/15 px-3 py-1 text-xs font-semibold text-brand-200">
            #{tag}
          </span>
        ))}
      </div>
    </section>
  );
}
