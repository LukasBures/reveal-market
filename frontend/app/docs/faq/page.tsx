import type { Metadata } from "next";
import Link from "next/link";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("faq");

export default function FAQPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">FAQ</h1>
      <dl className="space-y-6">
        <div>
          <dt className="font-semibold text-white">What is Reveal Market?</dt>
          <dd className="text-slate-300">
            Reveal Market is a zk commit-and-reveal prediction market stack with a FastAPI backend, Foundry contracts,
            and a price streamer that keeps markets and search in sync.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-white">How do markets settle?</dt>
          <dd className="text-slate-300">
            Orders are committed privately, revealed with Groth16 proofs, and finalized on-chain with verifiable
            attestations. Caches are tagged so the API and frontend stay consistent.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-white">How can teams engage?</dt>
          <dd className="text-slate-300">
            Partners typically either launch a branded marketplace, provide liquidity, or integrate the public API for
            analytics. Share your use case via the{" "}
            <Link href="/contact" className="text-brand-300 underline">
              contact form
            </Link>{" "}
            for a tailored walkthrough.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-white">Where do updates ship?</dt>
          <dd className="text-slate-300">
            Roadmap and architecture updates are posted in the docs, and release notes land on the @RevealMarket feed.
          </dd>
        </div>
      </dl>
    </>
  );
}
