import Link from "next/link";
import { buildMetadata } from "@/lib/seo";

export const metadata = buildMetadata({
  title: "Reveal Market | Zero-Knowledge Prediction Markets",
  description:
    "Reveal Market combines privacy-preserving commit-and-reveal rails with institutional APIs, zk-settlement, and partner-ready storefronts.",
  path: "/",
  keywords: [
    "prediction markets",
    "zero knowledge",
    "institutional trading",
    "reveal market",
    "ai ready data",
  ],
});

const highlights = [
  {
    title: "Privacy-first order flow",
    description:
      "Commit/reveal plus zk proofs keep trader alpha invisible until settlement, unlocking enterprise participation.",
  },
  {
    title: "Institution-grade APIs",
    description:
      "FastAPI + Redis caching deliver sub-50ms responses for matching engines, dashboards, and AI co-pilots.",
  },
  {
    title: "Composable storefronts",
    description:
      "Next.js marketplace modules let partners ship branded experiences without re-platforming.",
  },
];

const stats = [
  { label: "zk-settled markets", value: "120+" },
  { label: "Feeds ingested daily", value: "5M+" },
  { label: "Target uptime", value: "99.9%" },
];

export default function HomePage() {
  return (
    <div className="bg-black text-white">
      <section className="mx-auto flex min-h-[70vh] max-w-6xl flex-col items-center justify-center px-4 py-20 text-center">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-400">
          Zero-knowledge markets for institutions
        </p>
        <h1 className="mt-4 text-5xl font-semibold sm:text-6xl">
          Private conviction. Public settlement.
        </h1>
        <p className="mt-6 max-w-3xl text-lg text-slate-300">
          Reveal Market fuses a zk-powered commit/reveal protocol, a hardened FastAPI backend, and investor-grade tooling
          so exchanges, DAOs, and AI desks can trade signal without leaking alpha.
        </p>
        <div className="mt-8 flex flex-col gap-4 sm:flex-row">
          <a
            className="rounded-full bg-white px-8 py-3 text-black font-semibold transition hover:bg-white/80"
            href="mailto:hello@revealmarket.xyz"
          >
            Book an investor briefing
          </a>
          <Link
            className="rounded-full border border-white/40 px-6 py-3 font-semibold text-white transition hover:bg-white/10"
            href="/docs"
          >
            Explore the investor docs
          </Link>
        </div>
        <div className="mt-10 grid w-full gap-4 sm:grid-cols-3">
          {stats.map((stat) => (
            <div key={stat.label} className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-3xl font-semibold text-white">{stat.value}</p>
              <p className="text-sm uppercase tracking-[0.2em] text-slate-400">
                {stat.label}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16">
        <div className="grid gap-6 md:grid-cols-3">
          {highlights.map((item) => (
            <div key={item.title} className="rounded-2xl border border-white/10 bg-white/5 p-6">
              <h2 className="text-xl font-semibold text-white">{item.title}</h2>
              <p className="mt-3 text-slate-300">{item.description}</p>
            </div>
          ))}
        </div>
        <div className="mt-12 rounded-2xl border border-white/10 bg-gradient-to-r from-brand-500/20 to-transparent p-6 text-left">
          <h3 className="text-2xl font-semibold text-white">AI-ready prediction data</h3>
          <p className="mt-3 text-slate-200">
            Structured resolution archives and streaming endpoints feed quantitative research desks and large language models.
            Every market delivers rich metadata, rake transparency, and canonical identifiers for training pipelines.
          </p>
        </div>
      </section>

      <section className="bg-[#050a1a] py-16">
        <div className="mx-auto flex max-w-4xl flex-col items-center gap-6 px-4 text-center">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-500">
            Connect
          </p>
          <p className="text-slate-300">
            Daily updates drop on
            <a
              href="https://x.com/RevealMarket"
              className="ml-2 text-brand-200 underline"
              target="_blank"
              rel="noreferrer"
            >
              @RevealMarket
            </a>
            . Join the partner waitlist for data room access and product briefings.
          </p>
        </div>
      </section>
    </div>
  );
}
