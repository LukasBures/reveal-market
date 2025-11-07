import Link from "next/link";

export function Hero() {
  return (
    <section className="mx-auto flex max-w-4xl flex-col items-center gap-6 px-4 py-16 text-center">
      <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.3em] text-slate-400">
        Zero-knowledge reveals
      </span>
      <h1 className="text-4xl font-semibold tracking-tight text-white md:text-5xl">
        Trade high-signal events without exposing your edge.
      </h1>
      <p className="text-lg text-slate-300 md:text-xl">
        Reveal Market pairs commit-reveal mechanics with zk-proofs so you can
        participate in prediction markets, keep your alpha private, and receive
        provably fair payouts.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-4">
        <Link
          href="/docs/getting-started"
          className="rounded-full bg-brand-500 px-6 py-3 font-semibold text-white shadow-glow-brand transition hover:bg-brand-400"
        >
          Build on Reveal Market
        </Link>
        <Link
          href="https://docs.revealmarket.xyz"
          className="rounded-full border border-white/20 px-6 py-3 font-semibold text-white/80 transition hover:border-white hover:text-white"
        >
          Read docs
        </Link>
      </div>
    </section>
  );
}
