import type { Metadata } from "next";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Disclaimer",
  description: "Disclosure on informational use, investment risk, and jurisdictional restrictions.",
  path: "/disclaimer",
  keywords: ["disclaimer", "investment risk", "legal"],
  type: "article",
});

export default function DisclaimerPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Disclaimer", path: "/disclaimer" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "Reveal Market Disclaimer",
    description: "Disclosure on informational use, investment risk, and jurisdictional restrictions.",
    path: "/disclaimer",
    dateModified: "2026-02-18",
  });
  return (
    <>
      <section className="mx-auto max-w-7xl space-y-8 px-4 py-12 text-slate-200 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Legal</p>
        <h1 className="text-3xl font-semibold text-white sm:text-4xl">Disclaimer</h1>
        <p className="text-base text-slate-300 sm:text-lg">
          Reveal Market provides experimental software and informational materials. Nothing on this site constitutes
          financial, legal, tax, or investment advice.
        </p>
        <div className="space-y-6">
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">No Advice or Recommendations</h2>
            <p className="mt-3 text-slate-200">
              Any data, analytics, or commentary is provided for informational purposes only. You are solely
              responsible for your decisions and should consult qualified professionals where appropriate.
            </p>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Market and Technology Risks</h2>
            <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
              <li>Markets may be volatile, thinly traded, or unavailable.</li>
              <li>Smart contracts and integrations can fail or be exploited.</li>
              <li>Network congestion, forks, or outages can delay or prevent transactions.</li>
            </ul>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">No Custody, No Guarantees</h2>
            <p className="mt-3 text-slate-200">
              Reveal Market does not hold or control user funds. We do not guarantee uptime, liquidity, outcomes,
              or payouts. All interactions with wallets or smart contracts occur at your own risk.
            </p>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Jurisdiction and Eligibility</h2>
            <p className="mt-3 text-slate-200">
              You are responsible for understanding whether you may access or use the services. Use may be restricted
              or prohibited in certain jurisdictions.
            </p>
          </div>
        </div>
        <p className="text-sm text-slate-400">
          Use the platform responsibly and consult professionals if you have legal, regulatory, or tax questions.
        </p>
        <p className="text-sm text-slate-400">Last updated February 18, 2026.</p>
      </section>
      <JsonLd data={breadcrumbs} id="disclaimer-breadcrumbs" />
      <JsonLd data={articleSchema} id="disclaimer-article" />
    </>
  );
}
