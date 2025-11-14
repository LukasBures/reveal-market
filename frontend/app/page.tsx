import Link from "next/link";
import type { Metadata } from "next";
import { Suspense } from "react";
import { MarketFilters } from "@/components/markets/MarketFilters";
import { FeaturedMarketsSection, FeaturedMarketsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { buildMetadata } from "@/lib/seo";
import { fetchInvestorKpis, fetchMarketStatsBreakdown } from "@/lib/api";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market | Live Prediction Markets",
  description:
    "Browse institutional-grade prediction markets powered by Reveal Market’s zk-settlement stack.",
  path: "/",
  keywords: [
    "institutional prediction markets",
    "zero knowledge settlement",
    "onchain derivatives trading",
    "crypto event forecasting",
    "sports and politics odds",
    "Base chain markets",
    "decentralized risk exchange",
    "Reveal Market platform",
  ],
});

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

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: PageProps) {
  const [stats, kpis] = await Promise.all([fetchMarketStatsBreakdown(), fetchInvestorKpis()]);
  const totalMarkets = stats.reduce((sum, stat) => sum + stat.count, 0);
  const liveMarkets = stats
    .filter((stat) => ["commit", "locked"].includes(stat.status))
    .reduce((sum, stat) => sum + stat.count, 0);
  const callouts = [
    { label: "Markets live", value: liveMarkets > 0 ? liveMarkets.toLocaleString() : "—" },
    { label: "Total markets tracked", value: totalMarkets > 0 ? totalMarkets.toLocaleString() : "—" },
    { label: "Audit-ready proofs", value: "Groth16" },
  ];

  const resolvedParams = (await searchParams) ?? {};
  const rawSearchQuery = typeof resolvedParams.q === "string" ? resolvedParams.q : undefined;
  const normalizedSearch = rawSearchQuery?.trim() ?? "";
  const hasShortSearch = normalizedSearch.length > 0 && normalizedSearch.length < 2;
  const effectiveSearchQuery = hasShortSearch ? undefined : normalizedSearch || undefined;
  const searchNotice = hasShortSearch ? "Enter at least two characters to search markets." : undefined;

  return (
    <div className="bg-gradient-to-b from-slate-950 via-slate-950 to-black text-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-10">
        <div className="flex flex-col gap-4">
          <MarketFilters
            initialSearch={rawSearchQuery}
            liveMarketsCount={liveMarkets}
            totalMarketsCount={totalMarkets}
          />
        </div>
        <Suspense fallback={<FeaturedMarketsSkeleton />}>
          <FeaturedMarketsSection searchQuery={effectiveSearchQuery} emptyNotice={searchNotice} />
        </Suspense>
        <section className="glass-panel grid gap-4 p-6 text-sm text-slate-300 md:grid-cols-4">
          {callouts.map((item) => (
            <div key={item.label} className="rounded-2xl border border-white/10 bg-slate-950/60 p-4 text-center md:text-left">
              <p className="text-xs uppercase tracking-[0.35em] text-slate-500">{item.label}</p>
              <p className="mt-2 text-2xl font-semibold text-white text-glow">{item.value}</p>
            </div>
          ))}
        </section>
        <section className="grid gap-4 rounded-3xl border border-white/5 bg-slate-900/50 p-6 text-sm text-slate-300 lg:grid-cols-3">
          {featuredArticles.map((article) => (
            <Link
              key={article.title}
              href={article.href}
              className="rounded-2xl border border-white/5 bg-slate-950/40 p-5 text-center transition hover:border-brand-400/60 md:text-left"
            >
              <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Docs</p>
              <h3 className="mt-2 text-xl font-semibold text-white">{article.title}</h3>
              <p className="mt-2 text-slate-300">{article.description}</p>
            </Link>
          ))}
        </section>
      </div>
      <section className="relative overflow-hidden bg-slate-950/80 py-16">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-brand-500/10 to-transparent" />
        <div className="mx-auto flex max-w-5xl flex-col items-center gap-6 px-4 text-center">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">Need a bespoke feed?</p>
          <p className="text-lg text-slate-200">
            Email{" "}
            <a href="mailto:hello@revealmarket.xyz" className="text-brand-200 underline underline-offset-4">
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
