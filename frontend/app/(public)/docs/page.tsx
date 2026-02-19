import type { Metadata } from "next";
import Link from "next/link";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("overview"),
  description:
    "Docs for Reveal Market: how it works, what we share with users, and the stage-by-stage flow.",
  keywords: [
    "prediction markets docs",
    "how it works",
    "commit reveal",
    "settlement",
    "claims",
  ],
};

export default function DocsOverview() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Docs</p>
      <h1 className="text-4xl font-semibold text-white">How Reveal Market works</h1>
      <p className="text-lg text-slate-300">
        A straight-through guide to the flow, from access to settlement. This page explains the stages and how to
        participate without exposing private order flow.
      </p>
      <div className="space-y-8">
        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">How It Works</p>
          <p className="mt-3 text-slate-200">
            Reveal Market uses a staged flow to keep participation private while markets are live, then publishes
            clear settlement receipts once outcomes are final.
          </p>
          <ol className="mt-4 list-decimal space-y-3 pl-6 text-slate-200">
            <li>
              <strong>Stage 1 — Access.</strong> Get access to a board and review the rules and status before
              committing.
            </li>
            <li>
              <strong>Stage 2 — Quote.</strong> Request a signed quote for the ticket size you want, including price
              caps and expiry.
            </li>
            <li>
              <strong>Stage 3 — Commit.</strong> Commit your ticket privately. Your intent is recorded without
              broadcasting order flow.
            </li>
            <li>
              <strong>Stage 4 — Resolve.</strong> Once the market resolves, settlement data is published.
            </li>
            <li>
              <strong>Stage 5 — Claim.</strong> If you won, claim using the published receipt.
            </li>
          </ol>
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">What We Share With You</p>
          <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
            <li>Market status, rules, and the available outcomes before you commit.</li>
            <li>Signed quotes that show the ticket price, caps, and expiry window.</li>
            <li>Settlement receipts after resolution so you can verify outcomes and payouts.</li>
            <li>Public, on-chain confirmations for your own commits and claims.</li>
          </ul>
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">Privacy, By Design</p>
          <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
            <li>Commits are private while the market is live.</li>
            <li>Order flow is not broadcast in real time.</li>
            <li>Receipts are published only after the outcome is final.</li>
          </ul>
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">How To Participate</p>
          <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
            <li>Connect a wallet and review a market’s rules and status.</li>
            <li>Request a quote for a fixed ticket size and confirm the expiry window.</li>
            <li>Commit once you’re ready; the ticket is locked until resolution.</li>
            <li>Monitor resolution updates and claim if your outcome wins.</li>
          </ul>
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">Why This Flow</p>
          <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
            <li>Reduces information leakage while markets are live.</li>
            <li>Provides consistent pricing with signed quotes and caps.</li>
            <li>Publishes clear receipts so outcomes are verifiable after settlement.</li>
          </ul>
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-sm uppercase tracking-[0.3em] text-slate-400">What We Don’t Do</p>
          <ul className="mt-3 list-disc space-y-3 pl-6 text-slate-200">
            <li>We don’t custody your funds.</li>
            <li>We don’t guarantee outcomes, liquidity, or profits.</li>
            <li>We don’t broadcast private commits while markets are live.</li>
          </ul>
        </section>

      </div>
      <DocsStructuredData slug="overview" />
    </>
  );
}
