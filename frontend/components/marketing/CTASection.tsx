import Link from "next/link";

export function CTASection() {
  return (
    <section className="mx-auto max-w-5xl rounded-3xl border border-white/10 bg-gradient-to-r from-brand-600 to-brand-500 px-6 py-10 text-center shadow-2xl">
      <h3 className="text-2xl font-semibold text-white">
        Ready to launch your own zk-powered markets?
      </h3>
      <p className="mt-3 text-lg text-white/80">
        Deploy with our MarketFactory contract, or fork the worker + API stack
        to gain full control over ingestion, settlement, and payouts.
      </p>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
        <Link
          href="/docs/architecture"
          className="rounded-full bg-white px-5 py-2 font-semibold text-brand-600 shadow-lg transition hover:bg-white/90"
        >
          Explore architecture
        </Link>
        <Link
          href="https://github.com/RevealMarket"
          className="rounded-full border border-white/70 px-5 py-2 font-semibold text-white transition hover:border-white hover:bg-white/10"
        >
          View source
        </Link>
      </div>
    </section>
  );
}
