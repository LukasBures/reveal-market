import Image from "next/image";
import Link from "next/link";

type HeroStat = {
  label: string;
  value: string;
};

const heroHighlights = [
  {
    title: "Horizen aligned",
    description: "Base mainnet + zk Groth16 proofs",
  },
  {
    title: "Alpha-safe routing",
    description: "Commit → lock → reveal without leakage",
  },
  {
    title: "Institutional custody",
    description: "Ops desk + compliance ready from day one",
  },
] as const;

type HeroProps = {
  stats: HeroStat[];
};

export function Hero({ stats }: HeroProps) {
  return (
    <section className="relative overflow-hidden px-4 pb-12 pt-16">
      <div className="pointer-events-none absolute inset-x-4 top-8 h-64 rounded-full bg-brand-500/20 blur-[120px]" />
      <div className="relative mx-auto grid max-w-6xl gap-10 rounded-[32px] border border-white/10 bg-gradient-to-br from-brand-900/30 via-black/60 to-midnight-500/40 p-8 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-6">
          <div className="inline-flex items-center gap-3 rounded-full border border-white/15 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.4em] text-white/80">
            <Image src="/brand/reveal-mark.svg" alt="Reveal Market sigil" width={22} height={32} className="opacity-90" />
            Horizen ready · ZK native
          </div>
          <h1 className="font-display text-4xl leading-tight text-white md:text-5xl">
            Settle conviction without leaking alpha.
          </h1>
          <p className="text-lg text-slate-200 md:text-xl">
            Reveal Market gives institutional desks zk-settled commit-and-reveal rails, Groth16 proofs, and unified APIs
            so every market trade, rake split, and proof receipt clears instantly.
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <Link
              href="/docs/getting-started"
              className="rounded-full bg-brand-500 px-6 py-3 font-semibold text-white shadow-glow-brand transition hover:bg-brand-400"
            >
              Launch markets
            </Link>
            <Link
              href="/about"
              className="rounded-full border border-white/20 px-6 py-3 font-semibold text-white/80 transition hover:border-white hover:text-white"
            >
              Meet the team
            </Link>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {stats.map((stat) => (
              <div key={stat.label} className="rounded-2xl border border-white/10 bg-black/30 p-4">
                <p className="text-xs uppercase tracking-[0.3em] text-white/60">{stat.label}</p>
                <p className="mt-2 text-2xl font-semibold text-white">{stat.value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="relative overflow-hidden rounded-[28px] border border-white/15 bg-gradient-to-b from-brand-700/30 via-midnight-500/40 to-black/70 p-6">
          <div className="pointer-events-none absolute -right-24 top-6 h-48 w-48 rounded-full bg-brand-500/30 blur-[120px]" />
          <div className="pointer-events-none absolute -left-16 bottom-0 h-48 w-48 rounded-full bg-accent-400/15 blur-[100px]" />
          <div className="relative flex flex-col items-center gap-5 text-center">
            <div className="rounded-[24px] border border-white/20 bg-white/10 p-6 shadow-inner">
              <Image src="/brand/reveal-wolf.png" alt="Reveal Market wolf avatar" width={120} height={120} priority />
            </div>
            <p className="text-sm uppercase tracking-[0.35em] text-white/60">Signal wolfpack</p>
            <p className="text-2xl font-semibold text-white">Continuous risk ops.</p>
            <p className="text-base text-slate-200">
              Wolf badges flag every on-chain intervention, oracle pause, and zk proof push. Investors always know how the
              venue is defended.
            </p>
            <ul className="w-full space-y-3 text-left text-sm text-slate-200">
              {heroHighlights.map((highlight) => (
                <li key={highlight.title} className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/5 p-3">
                  <span className="mt-1 h-2.5 w-2.5 rounded-full bg-accent-400 shadow-[0_0_15px_rgba(123,240,94,0.6)]" />
                  <span>
                    <span className="block text-white">{highlight.title}</span>
                    <span className="text-white/70">{highlight.description}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
