import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/seo/JsonLd";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { buildFaqJsonLd, docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("faq");

const faqs = [
  {
    question: "What is Reveal Market?",
    answer:
      "Reveal Market is a zk commit-and-reveal prediction market stack with a FastAPI backend, Foundry contracts, and a streamer service that keeps markets and search in sync.",
  },
  {
    question: "How do markets settle?",
    answer:
      "Orders are committed privately, revealed with Groth16 proofs, and finalized on-chain with verifiable attestations. Caches are tagged so the API and frontend stay consistent.",
  },
  {
    question: "How can teams engage?",
    answer:
      "Partners typically either launch a branded marketplace, provide liquidity, or integrate the public API for analytics.",
    extra: (
      <>
        {" "}
        Share your use case via the{" "}
        <Link href="/contact" className="text-brand-300 underline">
          contact form
        </Link>{" "}
        for a tailored walkthrough.
      </>
    ),
  },
  {
    question: "Where do updates ship?",
    answer: "Roadmap and architecture updates are posted in the docs, and release notes land on the @RevealMarket feed.",
    extra: (
      <>
        {" "}
        Follow{" "}
        <a href="https://x.com/RevealMarket" target="_blank" rel="noreferrer" className="text-brand-300 underline">
          @RevealMarket
        </a>{" "}
        for day-to-day updates.
      </>
    ),
  },
];

export default function FAQPage() {
  const faqSchema = buildFaqJsonLd(
    faqs.map(({ question, answer }) => ({ question, answer })),
    "/docs/faq",
  );
  return (
    <>
      <h1 className="text-3xl font-semibold text-white">FAQ</h1>
      <dl className="space-y-6">
        {faqs.map((faq) => (
          <div key={faq.question}>
            <dt className="font-semibold text-white">{faq.question}</dt>
            <dd className="text-slate-300">
              {faq.answer}
              {faq.extra ?? null}
            </dd>
          </div>
        ))}
      </dl>
      <JsonLd data={faqSchema} id="faq-schema" />
      <DocsStructuredData slug="faq" />
    </>
  );
}
