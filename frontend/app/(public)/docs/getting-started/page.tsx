import type { Metadata } from "next";
import Link from "next/link";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("getting-started"),
  description:
    "How to start with Reveal Market: access, fund escrow, request signed quotes, commit privately, and claim after settlement.",
  keywords: [
    "getting started private prediction markets",
    "fixed ticket size",
    "signed quotes",
    "settlement receipts",
    "claim payouts",
  ],
};

export default function GettingStartedPage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Getting started</p>
      <h1 className="text-4xl font-semibold text-white">From access code to first claim</h1>
      <ol className="list-decimal space-y-6 pl-6 text-lg text-slate-300">
        <li>
          <h3 className="font-semibold text-white">Unlock access</h3>
          <p className="text-slate-300">
            Enter your access code on the landing page. If you need one, use the{" "}
            <Link href="/contact" className="text-brand-300 underline">
              contact form
            </Link>{" "}
            and we’ll help.
          </p>
        </li>
        <li>
          <h3 className="font-semibold text-white">Fund once</h3>
          <p className="text-slate-300">
            Approve and deposit into the escrow from your wallet. Funds stay in your control until you commit a fixed-size
            ticket in a private prediction market.
          </p>
        </li>
        <li>
          <h3 className="font-semibold text-white">Pick a market & get a quote</h3>
          <p className="text-slate-300">
            Browse featured markets, select an outcome, and request a signed quote. Quotes include caps and expiries so you
            know the bounds before you commit.
          </p>
        </li>
        <li>
          <h3 className="font-semibold text-white">Commit, then claim</h3>
          <p className="text-slate-300">
            Submit the quote to commit privately. When the outcome is final, read the published settlement receipt and
            claim your payout from escrow.
          </p>
        </li>
      </ol>
      <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
        Need help with access, funding, or claims? Reach out via{" "}
        <Link href="/contact" className="text-brand-300 underline">
          Contact
        </Link>{" "}
        and we’ll get you set up quickly.
      </div>
      <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
        Checklist: access code, wallet, deposit ready, signed quote, fixed ticket size understood.
      </div>
      <DocsStructuredData slug="getting-started" />
    </>
  );
}
