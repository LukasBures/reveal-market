import Link from "next/link";
import { fetchFeaturedMarkets } from "@/lib/api";
import { MarketFilters } from "@/components/markets/MarketFilters";
import { MarketGrid } from "@/components/markets/MarketGrid";
import { buildMetadata } from "@/lib/seo";

export const metadata = buildMetadata({
  title: "Reveal Market | Live Prediction Markets",
  description:
    "Browse institutional-grade prediction markets powered by Reveal Market’s zk-settlement stack.",
  path: "/",
  keywords: [
    "prediction markets",
    "zk markets",
    "crypto markets",
    "sports prediction",
    "politics prediction",
  ],
});

const callouts = [
  { label: "Markets live", value: "120+" },
  { label: "Protocols mirrored", value: "5+" },
  { label: "Avg. settlement time", value: "< 30s" },
  { label: "Audit-ready proofs", value: "Groth16" },
];

const featuredArticles = [
  {
    title: "Market toolkit for exchanges",
    description: "Embed the API, worker, and contracts inside your venue with guardrails.",
    href: "/docs/integrations" as const,
  },
  {
    title: "Guardian + risk operations",
    description: "How Reveal Market pauses markets, rotates oracles, and enforces rake.",
    href: "/docs/privacy-security" as const,
  },
  {
    title: "Token-aligned incentives",
    description: "Upcoming fee splits and liquidity programs for Reveal Market partners.",
    href: "/docs/tokenomics" as const,
  },
];

export default async function HomePage() {
  const markets = await fetchFeaturedMarkets(18);

  return (
    <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-10">
        <MarketFilters />
        <section className="grid gap-6 rounded-3xl border border-white/5 bg-slate-900/40 p-6 text-sm text-slate-300 md:grid-cols-4">
          {callouts.map((item) => (
            <div key={item.label} className="rounded-2xl border border-white/10 bg-slate-950/60 p-4">
              <p className="text-xs uppercase tracking-[0.35em] text-slate-500">{item.label}</p>
              <p className="mt-2 text-2xl font-semibold text-white">{item.value}</p>
            </div>
          ))}
        </section>
        <MarketGrid markets={markets} />
        <section className="grid gap-4 rounded-3xl border border-white/5 bg-slate-900/50 p-6 text-sm text-slate-300 lg:grid-cols-3">
          {featuredArticles.map((article) => (
            <Link
              key={article.title}
              href={article.href}
              className="rounded-2xl border border-white/5 bg-slate-950/40 p-5 transition hover:border-brand-400/60"
            >
              <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Docs</p>
              <h3 className="mt-2 text-xl font-semibold text-white">{article.title}</h3>
              <p className="mt-2 text-slate-300">{article.description}</p>
            </Link>
          ))}
        </section>
      </div>
      <section className="bg-slate-950/80 py-16">
        <div className="mx-auto flex max-w-5xl flex-col items-center gap-6 px-4 text-center">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-500">Need a bespoke feed?</p>
          <p className="text-slate-300">
            Email{" "}
            <a href="mailto:hello@revealmarket.xyz" className="text-brand-200 underline">
              hello@revealmarket.xyz
            </a>{" "}
            for curated endpoints, rake splits, and zk audit logs tailored to your venue.
          </p>
          <Link
            href="/docs"
            className="rounded-full border border-white/40 px-8 py-3 font-semibold text-white transition hover:bg-white/10"
          >
            Browse Documentation
          </Link>
        </div>
      </section>
    </div>
  );
}
