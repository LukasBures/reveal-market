import Link from "next/link";
import type { Metadata } from "next";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";

export const metadata: Metadata = buildMetadata({
  title: "About Reveal Market",
  description:
    "Reveal Market is a private prediction market platform built for serious traders. Commits stay private while markets are live, and every settlement is verified on-chain.",
  path: "/about",
  keywords: [
    "about reveal market",
    "private prediction markets",
    "commit reveal",
    "on-chain settlement",
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
      "Reveal Market is a private prediction market platform built for serious traders. Commits stay private while markets are live, and every settlement is verified on-chain.",
    path: "/about",
  });
  return (
    <>
      <div className="mx-auto max-w-7xl px-4 py-12 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">About</p>
        <h1 className="mt-2 text-3xl font-semibold text-white sm:text-4xl">Built for serious traders and on-chain builders.</h1>
        <p className="mt-4 text-base text-slate-300 sm:text-lg">
          Reveal Market uses a commit-and-reveal design that keeps your positions private until a market settles. Every
          payout is verified by a zero-knowledge proof, so outcomes are trustless and receipts are public.
        </p>
        <div className="mt-10 grid gap-6 md:grid-cols-2">
          <div className="rounded-2xl border border-white/10 p-5">
            <h2 className="text-xl font-semibold text-white">What’s live</h2>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-300">
              <li>Fast, reliable market data with real-time updates.</li>
              <li>Live event feeds synced from external sources to on-chain markets.</li>
              <li>Zero-knowledge proof contracts for trustless, verifiable settlement.</li>
            </ul>
          </div>
          <div className="rounded-2xl border border-white/10 p-5">
            <h2 className="text-xl font-semibold text-white">What’s next</h2>
            <ul className="mt-4 list-disc space-y-2 pl-5 text-slate-300">
              <li>Seamless wallet onboarding for new participants.</li>
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
