import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Cookie Policy",
  description: "How Reveal Market uses cookies and similar technologies, and how you can control them.",
  path: "/cookies",
  keywords: ["cookies", "policy", "tracking", "analytics", "preferences"],
  type: "article",
});

export default function CookiesPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Cookies", path: "/cookies" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "Reveal Market Cookie Policy",
    description: "How Reveal Market uses cookies and similar technologies, and how you can control them.",
    path: "/cookies",
    dateModified: "2026-02-18",
  });
  return (
    <>
      <section className="mx-auto max-w-7xl space-y-8 px-4 py-12 text-slate-200 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Legal</p>
        <h1 className="text-3xl font-semibold text-white sm:text-4xl">Cookie Policy</h1>
        <p className="text-base text-slate-300 sm:text-lg">
          We use cookies and similar technologies to operate the site, understand performance, and maintain security.
        </p>
        <div className="space-y-6">
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Types of Cookies We Use</h2>
            <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
              <li>
                <strong>Essential.</strong> Required for core functionality and security, such as session state and
                fraud prevention.
              </li>
              <li>
                <strong>Analytics.</strong> Aggregated metrics to understand usage and improve performance. Data is
                processed in a way that minimizes identification.
              </li>
              <li>
                <strong>Preference.</strong> Saves display preferences like language or layout choices.
              </li>
              <li>
                <strong>Third-party.</strong> Content delivery networks, embedded content, or documentation providers
                may set their own cookies.
              </li>
            </ul>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Your Controls</h2>
            <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
              <li>Adjust browser settings to block or delete cookies.</li>
              <li>Use private browsing modes to limit storage between sessions.</li>
              <li>Decline optional cookies when presented in site controls (if available).</li>
            </ul>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Do Not Track</h2>
            <p className="mt-3 text-slate-200">
              Some browsers send “Do Not Track” signals. We currently do not respond to these signals because there is
              no consistent industry standard.
            </p>
          </div>
        </div>
        <p className="text-sm text-slate-400">
          You can disable cookies in your browser settings, but some features may stop working. Questions? Use the{" "}
          <Link href="/contact" className="text-brand-300 underline">
            contact form
          </Link>
          .
        </p>
        <p className="text-sm text-slate-400">Last updated February 18, 2026.</p>
      </section>
      <JsonLd data={breadcrumbs} id="cookies-breadcrumbs" />
      <JsonLd data={articleSchema} id="cookies-article" />
    </>
  );
}
