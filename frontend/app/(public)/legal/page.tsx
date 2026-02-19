import Link from "next/link";
import type { Metadata } from "next";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Legal Center",
  description:
    "Centralized access to Reveal Market's terms, privacy policy, cookie disclosures, and regulatory disclaimers for partners and investors.",
  path: "/legal",
  keywords: ["legal", "privacy", "terms", "compliance", "reveal market"],
});

const legalLinks = [
  {
    href: "/terms" as const,
    label: "Terms of Use",
    description: "Rights, responsibilities, and acceptable use of Reveal Market.",
  },
  {
    href: "/privacy" as const,
    label: "Privacy Policy",
    description: "How we process personal data, analytics, and retention practices.",
  },
  {
    href: "/cookies" as const,
    label: "Cookie Notice",
    description: "Details on cookies, tracking tech, and opt-out options.",
  },
  {
    href: "/disclaimer" as const,
    label: "Regulatory Disclaimer",
    description: "Risk disclosures for investors, LPs, and exchange partners.",
  },
];

export default function LegalCenterPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Legal", path: "/legal" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "Reveal Market Legal Center",
    description:
      "Centralized access to Reveal Market's terms, privacy policy, cookie disclosures, and regulatory disclaimers for partners and investors.",
    path: "/legal",
  });
  return (
    <>
      <section className="mx-auto max-w-7xl space-y-6 px-4 py-12 text-slate-200 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Compliance</p>
        <h1 className="text-3xl font-semibold text-white sm:text-4xl">Reveal Market Legal Center</h1>
        <p className="text-base text-slate-300 sm:text-lg">
          Review the policies, disclosures, and notices that govern participation in the Reveal Market ecosystem. Each document
          below links to a dedicated page so compliance teams, partners, and investors can access the latest terms at any time.
        </p>
        <div className="space-y-4">
          {legalLinks.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="group block rounded-2xl border border-white/10 bg-white/5 p-5 shadow-[0_25px_60px_rgba(1,3,20,0.65)] transition duration-200 will-change-transform [backface-visibility:hidden] [transform:translateZ(0)] hover:-translate-y-1.5 hover:border-brand-400/60 hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300/70"
            >
              <p className="text-sm uppercase tracking-[0.25em] text-slate-500 transition group-hover:text-slate-300 sm:tracking-[0.3em]">
                {item.label}
              </p>
              <p className="mt-2 text-slate-200">{item.description}</p>
              <span className="mt-3 inline-flex items-center text-sm font-semibold text-brand-200 transition group-hover:text-brand-100">
                Read {item.label}
              </span>
            </Link>
          ))}
        </div>
        <p className="text-sm text-slate-400">
          For additional legal inquiries or signed agreements, submit a note through the{" "}
          <Link href="/contact" className="text-brand-200 underline">
            contact form
          </Link>
          .
        </p>
      </section>
      <JsonLd data={breadcrumbs} id="legal-breadcrumbs" />
      <JsonLd data={articleSchema} id="legal-article" />
    </>
  );
}
