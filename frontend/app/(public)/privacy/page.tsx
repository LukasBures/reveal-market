import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Privacy Policy",
  description: "How Reveal Market collects, uses, and protects visitor information and operational data.",
  path: "/privacy",
  keywords: ["privacy", "policy", "data protection", "data retention", "security"],
  type: "article",
});

export default function PrivacyPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Privacy", path: "/privacy" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "Reveal Market Privacy Policy",
    description: "How Reveal Market collects, uses, and protects visitor information and operational data.",
    path: "/privacy",
    dateModified: "2026-02-18",
  });
  return (
    <>
      <section className="mx-auto max-w-7xl space-y-8 px-4 py-12 text-slate-200 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Legal</p>
        <h1 className="text-3xl font-semibold text-white sm:text-4xl">Privacy Policy</h1>
        <p className="text-base text-slate-300 sm:text-lg">
          We keep data collection lean and operational. This policy explains what we collect, why we collect it, and
          how you can control it.
        </p>
        <div className="space-y-6">
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Information We Collect</h2>
            <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
              <li>
                <strong>Operational and security logs.</strong> Server logs capture timestamps, request metadata, error
                traces, and security events to keep the platform stable and safe.
              </li>
              <li>
                <strong>Usage analytics.</strong> We collect aggregated metrics (page views, performance, feature
                usage) to improve reliability and user experience.
              </li>
              <li>
                <strong>Contact data.</strong> If you use the contact form, we receive your message and contact details
                so we can respond.
              </li>
              <li>
                <strong>Blockchain activity.</strong> Public on-chain data may be displayed or referenced when you
                interact with smart contracts or public market data.
              </li>
            </ul>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">How We Use Data</h2>
            <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
              <li>Provide, secure, and maintain the services.</li>
              <li>Monitor performance, troubleshoot issues, and prevent abuse.</li>
              <li>Respond to requests or inquiries you send us.</li>
            </ul>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Data Sharing</h2>
            <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
              <li>
                We do not sell personal information.
              </li>
              <li>
                We may share limited data with infrastructure providers, analytics vendors, or security partners that
                help us operate the site.
              </li>
              <li>
                We may disclose information to comply with legal obligations or protect the safety and security of the
                services.
              </li>
            </ul>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Data Retention</h2>
            <p className="mt-3 text-slate-200">
              We keep data only as long as needed for operations, security, and compliance. Retention periods vary by
              data type and legal obligations.
            </p>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">Your Choices</h2>
            <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
              <li>Block cookies through your browser settings. See the Cookie Policy for details.</li>
              <li>Choose whether to share information through the contact form.</li>
              <li>Use privacy tools (VPNs, privacy browsers) at your discretion.</li>
            </ul>
          </div>
          <div>
            <h2 className="text-sm uppercase tracking-[0.3em] text-slate-400">International Use</h2>
            <p className="mt-3 text-slate-200">
              The services are available globally. By using them, you understand that data may be processed where our
              infrastructure providers operate.
            </p>
          </div>
        </div>
        <p className="text-sm text-slate-400">
          Questions? Use the{" "}
          <Link href="/contact" className="text-brand-300 underline">
            contact form
          </Link>{" "}
          and we will respond directly.
        </p>
        <p className="text-sm text-slate-400">Last updated February 18, 2026.</p>
      </section>
      <JsonLd data={breadcrumbs} id="privacy-breadcrumbs" />
      <JsonLd data={articleSchema} id="privacy-article" />
    </>
  );
}
