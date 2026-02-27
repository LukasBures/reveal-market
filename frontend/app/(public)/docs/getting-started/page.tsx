import type { Metadata } from "next";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("getting-started"),
  description:
    "Get access, connect a wallet, request a signed quote, commit a ticket, and claim after settlement. A quick start guide for new participants ready to begin.",
  keywords: [
    "getting started",
    "commit",
    "settlement",
    "claims",
  ],
};

export default function GettingStartedPage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Getting started</p>
      <h1 className="text-4xl font-semibold text-white">From access to first claim</h1>
      <ol className="list-decimal space-y-6 pl-6 text-lg text-slate-300">
        <li>
          <h2 className="text-lg font-semibold text-white !text-lg">Open the app</h2>
          <p className="text-slate-300">
            Visit the homepage and connect your wallet when you are ready to participate.
          </p>
        </li>
        <li>
          <h2 className="text-lg font-semibold text-white !text-lg">Prepare funds</h2>
          <p className="text-slate-300">
            Keep funds ready in your wallet. You stay in control until you commit a ticket.
          </p>
        </li>
        <li>
          <h2 className="text-lg font-semibold text-white !text-lg">Pick a market & get a quote</h2>
          <p className="text-slate-300">
            Select an outcome and request a signed quote. Quotes include caps and expiries so you know the bounds before
            you commit.
          </p>
        </li>
        <li>
          <h2 className="text-lg font-semibold text-white !text-lg">Commit, then claim</h2>
          <p className="text-slate-300">
            Submit the quote to commit privately. When the outcome is final, read the receipt and claim your payout.
          </p>
        </li>
      </ol>
      <DocsStructuredData slug="getting-started" />
    </>
  );
}
