import Link from "next/link";
import type { Metadata } from "next";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";

export const metadata: Metadata = buildMetadata({
  title: "About Reveal Market",
  description:
    "Reveal Market pairs zero-knowledge prediction rails with institution-ready infrastructure and a clear roadmap.",
  path: "/about",
  keywords: [
    "about reveal market",
    "prediction market team",
    "institutional infrastructure",
  ],
  type: "article",
});

export default function AboutPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "About", path: "/about" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "About Reveal Market",
    description:
      "Reveal Market pairs zero-knowledge prediction rails with institution-ready infrastructure and a clear roadmap.",
    path: "/about",
  });
  return (
    <>
      <div className="mx-auto max-w-7xl px-4 py-12 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">About</p>
        <h1 className="mt-2 text-3xl font-semibold text-white sm:text-4xl">Built for high-signal traders & builders.</h1>
        <p className="mt-4 text-base text-slate-300 sm:text-lg">
          Reveal Market couples a hardened FastAPI backend, async ingestion worker, Redis edge caching, and Foundry-based
          smart contracts. Our commit-and-reveal design keeps alpha private until settlement, while zk-proof verification
          ensures payouts remain trustless.
        </p>
        <div className="mt-10 grid gap-6 md:grid-cols-2">
          <div className="rounded-2xl border border-white/10 p-5">
            <h2 className="text-xl font-semibold text-white">What’s live</h2>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-300">
              <li>FastAPI read/write surface with Redis-backed caching.</li>
              <li>Worker daemon syncing external feeds alongside on-chain deployments.</li>
              <li>zk-powered RevealMarket + MarketFactory contracts.</li>
            </ul>
          </div>
          <div className="rounded-2xl border border-white/10 p-5">
            <h2 className="text-xl font-semibold text-white">What’s next</h2>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-300">
              <li>Wallet-native onboarding with Wagmi + RainbowKit.</li>
              <li>Horizen and Polygon deployment presets.</li>
              <li>Full docs library at revealmarket.xyz/docs.</li>
            </ul>
          </div>
        </div>
        <div className="mt-10 rounded-2xl border border-white/10 bg-white/5 p-6">
          <h2 className="text-2xl font-semibold text-white">Questions?</h2>
          <p className="mt-3 text-slate-300">
            Read the{" "}
            <Link
              href="/docs"
              className="text-brand-300 underline decoration-brand-400"
            >
              docs
            </Link>{" "}
            or reach out via the{" "}
            <Link href="/contact" className="text-brand-300 underline decoration-brand-400">
              contact form
            </Link>
            .
          </p>
        </div>
      </div>
      <JsonLd data={breadcrumbs} id="about-breadcrumbs" />
      <JsonLd data={articleSchema} id="about-article" />
    </>
  );
}
