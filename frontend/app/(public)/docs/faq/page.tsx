import type { Metadata } from "next";
import Link from "next/link";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildFaqJsonLd, docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("faq"),
  description:
    "FAQ for Reveal Market: participation, settlement, and claims.",
  keywords: [
    "faq",
    "settlement",
    "claims",
    "how it works",
  ],
};

const faqs = [
  {
    question: "What is Reveal Market?",
    answer:
      "Reveal Market runs fixed-ticket private prediction markets. Commits stay private while markets are live, and every settlement publishes a clear receipt you can read without jargon.",
  },
  {
    question: "How do markets settle?",
    answer:
      "Tickets are locked, the winning outcome is posted, and a receipt is published. Claims are paid out to the committing wallet after settlement.",
  },
  {
    question: "How do I start trading?",
    answer:
      "Connect your wallet, request a signed quote, and submit it to commit privately.",
    extra: (
      <>
        {" "}
        The{" "}
        <Link href="/docs/getting-started" className="text-brand-300 underline">
          Getting Started guide
        </Link>{" "}
        walks through each step.
      </>
    ),
  },
  {
    question: "How can I verify outcomes?",
    answer: "Every resolved market includes a published receipt that summarizes the result and payouts for that market.",
    extra: (
      <>
        {" "}
        See the{" "}
        <Link href="/proofs" className="text-brand-300 underline">
          Proofs
        </Link>{" "}
        page for recent receipts and statuses.
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
      <p className="text-xs uppercase tracking-[0.35em] text-slate-400">FAQ</p>
      <h1 className="text-4xl font-semibold text-white">Frequently asked questions</h1>
      <dl className="space-y-6 text-lg text-slate-300">
        {faqs.map((faq) => (
          <div key={faq.question}>
            <dt className="text-lg font-semibold text-white">{faq.question}</dt>
            <dd className="text-slate-300">
              {faq.answer}
              {faq.extra ?? null}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-6 text-sm text-slate-300">
        Still have questions? Review the docs sections on the left for more detail.
      </p>
      <JsonLd data={faqSchema} id="faq-schema" />
      <DocsStructuredData slug="faq" />
    </>
  );
}
