import Link from "next/link";
import { fetchInvestorKpis } from "../lib/api";
import { buildMetadata } from "../lib/seo";

export const metadata = buildMetadata({
  title: "Reveal Market | Investor-Grade Prediction Markets",
  description:
    "A zk-powered prediction stack with real-time KPIs, auditable rake sharing, and partner-ready storefronts for institutional liquidity.",
  path: "/",
  keywords: [
    "institutional prediction markets",
    "zk settlement",
    "investor briefing",
    "liquidity partners",
    "rake transparency",
  ],
});

const proofPoints = [
  {
    title: "Attested settlement layer",
    description:
      "Groth16 proofs, Conditional Tokens snapshots, and an ingestion worker that logs every payout vector back into Postgres + Redis.",
  },
  {
    title: "Treasury-grade observability",
    description:
      "Unified logging, Prometheus metrics, and schema-versioned caches keep diligence teams aligned on the exact data serving LP dashboards.",
  },
  {
    title: "Partner storefront rails",
    description:
      "Composable Next.js modules, embed widgets, and API keys tied to rake splits let funds launch branded surfaces without re-platforming.",
  },
];

const testimonials = [
  {
    quote:
      "Reveal’s API latency and cache-tag strategy mirror what we expect from Tier-1 trading venues.",
    author: "CTO, regulated exchange",
    context: "Pre-launch diligence call",
  },
  {
    quote:
      "The commit/reveal model protects LP alpha while still giving us a verifiable audit trail for investors.",
    author: "Partner fund lead",
    context: "Liquidity partnership memo",
  },
  {
    quote:
      "Having rake, guardian state, and settlement metadata on every payload simplified our compliance review.",
    author: "Head of risk, market-maker",
    context: "Integration workshop",
  },
];

const numberFormatter = new Intl.NumberFormat("en-US");

function formatCount(value: number) {
  return numberFormatter.format(value);
}

function formatLatency(value: number | null) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return `${value.toFixed(1)} ms`;
  }
  return "—";
}

export default async function HomePage() {
  const kpis = await fetchInvestorKpis();
  const updatedAt = kpis.lastUpdatedIso
    ? new Date(kpis.lastUpdatedIso).toLocaleString()
    : null;

  const statCards = [
    {
      label: "Open liquidity programs",
      value: formatCount(kpis.openMarkets),
      source: "API /markets/stats (commit + locked)",
    },
    {
      label: "Settlements logged",
      value: formatCount(kpis.settledMarkets),
      source: "API /markets/stats (settled)",
    },
    {
      label: "Database median latency",
      value: formatLatency(kpis.databaseLatencyMs),
      source: "API /health · database component",
    },
    {
      label: "Rake transparency target",
      value: "99% markets",
      source: "Resolution ledger + rake manager attestations",
    },
  ];

  return (
    <div className="bg-black text-white">
      <section className="mx-auto flex min-h-[70vh] max-w-6xl flex-col items-center justify-center px-4 py-20 text-center">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-400">
          Investor briefing · Updated in real time
        </p>
        <h1 className="mt-4 text-5xl font-semibold sm:text-6xl">
          ZK-settled conviction with investor-grade KPIs.
        </h1>
        <p className="mt-6 max-w-3xl text-lg text-slate-300">
          Reveal Market fuses a zk-powered commit/reveal protocol, schema-aware caches, and a
          transparency-first storefront so exchanges, DAOs, and funds can model liquidity programs with live data.
        </p>
        <div className="mt-8 flex flex-col gap-4 sm:flex-row">
          <a
            className="rounded-full bg-white px-8 py-3 text-black font-semibold transition hover:bg-white/80"
            href="mailto:hello@revealmarket.xyz"
          >
            Connect with the team
          </a>
          <Link
            className="rounded-full border border-white/40 px-6 py-3 font-semibold text-white transition hover:bg-white/10"
            href="/docs"
          >
            Download the investor brief
          </Link>
        </div>
        <div className="mt-12 grid w-full gap-4 md:grid-cols-2 lg:grid-cols-4">
          {statCards.map((card) => (
            <div
              key={card.label}
              className="rounded-2xl border border-white/10 bg-white/5 p-5 text-left"
            >
              <p className="text-4xl font-semibold text-white">{card.value}</p>
              <p className="mt-2 text-sm font-medium uppercase tracking-[0.2em] text-slate-400">
                {card.label}
              </p>
              <p className="mt-3 text-xs text-slate-500">{card.source}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-slate-500">
          {updatedAt ? `Data refreshed ${updatedAt}` : "Live metrics sourced from the Reveal Market API."}
        </p>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16">
        <div className="grid gap-6 md:grid-cols-3">
          {proofPoints.map((item) => (
            <div key={item.title} className="rounded-2xl border border-white/10 bg-white/5 p-6">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Proof point</p>
              <h2 className="mt-2 text-xl font-semibold text-white">{item.title}</h2>
              <p className="mt-3 text-slate-300">{item.description}</p>
            </div>
          ))}
        </div>
        <div className="mt-12 rounded-2xl border border-white/10 bg-gradient-to-r from-brand-500/20 to-transparent p-6 text-left">
          <h3 className="text-2xl font-semibold text-white">AI-ready settlement data</h3>
          <p className="mt-3 text-slate-200">
            Structured resolution archives, per-market rake disclosures, and canonical identifiers feed quantitative
            research desks, AI copilots, and diligence war rooms. Every payload is tagged with schema revisions so
            auditors know exactly which migration produced it.
          </p>
        </div>
      </section>

      <section className="bg-slate-950/80 py-16">
        <div className="mx-auto max-w-6xl px-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Social proof</p>
          <h3 className="mt-3 text-3xl font-semibold text-white">
            Partners are already modeling liquidity on Reveal Market.
          </h3>
          <div className="mt-8 grid gap-6 md:grid-cols-3">
            {testimonials.map((item) => (
              <figure
                key={item.quote}
                className="rounded-2xl border border-white/10 bg-white/5 p-5 text-left"
              >
                <blockquote className="text-slate-200">&ldquo;{item.quote}&rdquo;</blockquote>
                <figcaption className="mt-4 text-sm text-slate-400">
                  <p className="font-semibold text-white">{item.author}</p>
                  <p>{item.context}</p>
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="mt-4 text-xs text-slate-500">
            Testimonials are anonymized, forward-looking statements; they are not guarantees of future performance.
          </p>
        </div>
      </section>

      <section className="bg-[#050a1a] py-16">
        <div className="mx-auto flex max-w-4xl flex-col items-center gap-6 px-4 text-center">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-500">Connect</p>
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
            . Join the partner waitlist for data room access, quarterly treasury breakdowns, and bespoke diligence calls.
          </p>
          <a
            href="mailto:hello@revealmarket.xyz?subject=Reveal%20Market%20Investor%20Briefing"
            className="rounded-full border border-white/40 px-8 py-3 font-semibold text-white transition hover:bg-white/10"
          >
            Request a diligence session
          </a>
        </div>
      </section>
    </div>
  );
}
