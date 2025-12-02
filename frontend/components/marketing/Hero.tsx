import Link from "next/link";
import Image from "next/image";

type HeroStat = {
  label: string;
  value: string;
};

const heroHighlights = [
  {
    title: "Hidden while live",
    description: "Entries stay sealed until the market settles, so sizing never hits a public board.",
  },
  {
    title: "Receipts on settle",
    description: "When outcomes post, everyone sees a clear, human-readable breakdown.",
  },
  {
    title: "Ops that talks",
    description: "Pauses, rule tweaks, and claims get called out before you make a move.",
  },
] as const;

type HeroProps = {
  stats: HeroStat[];
};

export function Hero({ stats }: HeroProps) {
  return (
    <section className="relative overflow-hidden px-4 pb-16 pt-20">
      <div className="pointer-events-none absolute inset-x-0 -top-32 h-96 bg-[radial-gradient(circle_at_50%_-10%,rgba(124,132,255,0.18),transparent_60%)] blur-[140px]" />
      <div className="relative mx-auto grid max-w-7xl gap-10 rounded-[40px] border border-white/10 bg-black/30 p-8 shadow-[0_40px_120px_-60px_rgba(14,21,56,0.9)] lg:grid-cols-[1.05fr_0.95fr]">
        <div className="space-y-8">
          <div className="inline-flex items-center gap-3 rounded-full border border-white/15 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.4em] text-white/80">
            <Image src="/brand/reveal-mark.svg" alt="Reveal Market sigil" width={22} height={32} className="opacity-90" />
            Private board · invite only
          </div>
          <div className="space-y-4">
            <h1 className="font-display text-4xl leading-tight text-white md:text-5xl lg:text-6xl">
              Trade the story without broadcasting your moves.
            </h1>
            <p className="text-base text-slate-200 md:text-lg">
              Reveal Market is an invite-only arena for conviction on sports, politics, and macro moments. Positions stay
              private while markets play out; when they settle, you get a clean receipt of who got paid and why.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {stats.map((stat) => (
              <div
                key={stat.label}
                className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-4 shadow-[0_20px_40px_rgba(0,0,0,0.35)]"
              >
                <div className="pointer-events-none absolute inset-x-4 top-2 h-16 rounded-full bg-gradient-to-r from-accent-400/20 via-white/10 to-brand-500/20 blur-3xl" />
                <p className="text-xs uppercase tracking-[0.3em] text-white/70">{stat.label}</p>
                <p className="mt-3 text-2xl font-semibold text-white">{stat.value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="wolf-aura p-6">
          <div className="relative flex h-full flex-col items-center gap-5 text-center">
            <div className="relative flex items-center justify-center">
              <div className="absolute inset-0 rounded-full bg-gradient-to-b from-white/40 via-white/10 to-transparent opacity-70 blur-3xl" />
              <img
                src="/brand/reveal-wolf-02.png"
                alt="Reveal Market wolf avatar"
                loading="eager"
                className="relative z-10 w-64 max-w-full drop-shadow-[0_35px_70px_rgba(0,0,0,0.55)]"
              />
            </div>
            <div className="aurora-divider" aria-hidden />
            <p className="text-xs uppercase tracking-[0.45em] text-white/60">Private member board</p>
            <p className="text-2xl font-semibold text-white">Built for discreet conviction</p>
            <p className="text-base text-slate-200">
              Badges light up when markets pause, rules change, or claims open. You see how the board is being run before
              you size up.
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
