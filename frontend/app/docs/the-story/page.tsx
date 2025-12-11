import type { Metadata } from "next";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("the-story");

export default function StoryPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">The Story</h1>
      <p className="text-slate-300">
        Reveal Market started as a response to a simple gap: high-signal traders would never share their edge in public
        order books, yet institutions still needed transparent, auditable settlements. We built commit-and-reveal rails so
        conviction could stay private until resolution, and paired them with structured logging, receipts, and zk proofs so
        compliance teams could trust the outcomes.
      </p>
      <p className="text-slate-300">
        The stack evolved alongside partner feedback—FastAPI for observability, a Redis-backed ingestion loop for freshness,
        Foundry contracts for determinism, and a frontend tuned for diligence-first narratives. Each iteration focused on
        reducing operational friction: schema-tagged caches, heartbeats, and health endpoints that keep markets indexable and
        verifiable without manual babysitting.
      </p>
      <p className="text-slate-300">
        Today the roadmap is pragmatic: harden privacy/security controls, automate liquidity ops, and ship the partner playbook
        that lets exchanges, LPs, and media brands launch their own Reveal-powered venues. The goal remains unchanged—make
        private, provable prediction markets a default primitive for serious capital.
      </p>
      <DocsStructuredData slug="the-story" />
    </>
  );
}
