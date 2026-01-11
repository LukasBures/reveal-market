import type { Metadata } from "next";
import Link from "next/link";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("overview"),
  description:
    "Docs for Reveal Market: private prediction markets with fixed tickets, signed quotes, and published settlement receipts.",
  keywords: [
    "private prediction markets docs",
    "fixed ticket size",
    "signed quotes",
    "settlement receipts",
    "claims",
  ],
};

export default function DocsOverview() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Docs</p>
      <h1 className="text-4xl font-semibold text-white">Reveal Market overview</h1>
      <p className="text-lg text-slate-300">
        High-level guidance on how Reveal Market works, who it’s for, and how to get started. These private prediction
        markets use fixed tickets, signed quotes with caps, and published settlement receipts so outcomes stay trusted.
      </p>
      <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5">
        <p className="text-sm font-semibold text-white">What&apos;s inside</p>
        <ul className="mt-3 space-y-2 text-slate-200">
          <li>
            <Link href="/docs/getting-started" className="text-brand-300 underline">
              Getting Started
            </Link>{" "}
            — access, fund escrow, request signed quotes, commit privately, claim after settlement.
          </li>
          <li>
            <Link href="/docs/privacy-security" className="text-brand-300 underline">
              Privacy & Security
            </Link>{" "}
            — private commits, access controls, published settlement receipts.
          </li>
          <li>
            <Link href="/docs/faq" className="text-brand-300 underline">
              FAQ
            </Link>{" "}
            — quick answers about fixed ticket size, signed quotes, and claims.
          </li>
        </ul>
      </div>
      <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
        Need access or more detail?{" "}
        <Link href="/contact" className="text-brand-300 underline">
          Contact us
        </Link>{" "}
        and we&apos;ll help.
      </div>
      <div className="mt-8 grid gap-6 md:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">At a glance</h2>
          <ul className="mt-3 space-y-2 text-slate-200">
            <li>• Private commits with fixed ticket sizes</li>
            <li>• Signed pricing with caps and expiries</li>
            <li>• Published settlement receipts for every resolved market</li>
            <li>• Simple claim flow once results are final</li>
          </ul>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <h2 className="text-xl font-semibold text-white">Read next</h2>
          <ul className="mt-3 space-y-2">
            <li>
              <Link href="/docs/getting-started" className="text-brand-300">
                Getting Started – unlock access, fund, and place your first ticket.
              </Link>
            </li>
            <li>
              <Link href="/docs/privacy-security" className="text-brand-300">
                Privacy & Security – how we keep commits private and settlements transparent.
              </Link>
            </li>
            <li>
              <Link href="/docs/faq" className="text-brand-300">
                FAQ – quick answers to common questions.
              </Link>
            </li>
          </ul>
        </div>
      </div>
      <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-5 text-sm text-slate-300">
        Need help or account access? Use the{" "}
        <Link href="/contact" className="text-brand-300 underline">
          contact form
        </Link>{" "}
        and we’ll follow up quickly.
      </div>
      <DocsStructuredData slug="overview" />
    </>
  );
}
