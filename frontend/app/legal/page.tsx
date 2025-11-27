import Link from "next/link";
import type { Metadata } from "next";
import { buildMetadata } from "@/lib/seo";

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
  return (
    <section className="mx-auto max-w-4xl space-y-6 px-4 py-12 text-slate-200">
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Compliance</p>
      <h1 className="text-3xl font-semibold text-white">Reveal Market Legal Center</h1>
      <p>
        Review the policies, disclosures, and notices that govern participation in the Reveal Market ecosystem. Each document
        below links to a dedicated page so compliance teams, partners, and investors can access the latest terms at any time.
      </p>
      <div className="space-y-4">
        {legalLinks.map((item) => (
          <div key={item.href} className="rounded-2xl border border-white/10 bg-white/5 p-5">
            <p className="text-sm uppercase tracking-[0.3em] text-slate-500">{item.label}</p>
            <p className="mt-2 text-slate-200">{item.description}</p>
            <Link
              href={item.href}
              className="mt-3 inline-flex items-center text-sm font-semibold text-brand-200 hover:text-brand-100"
            >
              Read {item.label}
            </Link>
          </div>
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
  );
}
