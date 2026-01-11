import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/seo/JsonLd";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { buildFaqJsonLd, docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("faq"),
  description:
    "FAQ for Reveal Market: private prediction markets, fixed ticket size, signed quotes, and published settlement receipts.",
  keywords: [
    "private prediction markets FAQ",
    "fixed ticket size",
    "signed quotes",
    "settlement receipts",
    "claims",
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
      "Tickets are locked, the winning outcome is posted, and a verifiable receipt is published. Claims are paid out to the committing wallet after settlement.",
  },
  {
    question: "How do I start trading?",
    answer:
      "Unlock access with your code, fund escrow once, request a signed quote, and submit it to commit privately.",
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
        page for recent receipts and statuses. Follow{" "}
        <a href="https://x.com/RevealMarket" target="_blank" rel="noreferrer" className="text-brand-300 underline">
          @RevealMarket
        </a>{" "}
        for updates.
      </>
    ),
  },
];

export default function FAQPage() {
  const faqSchema = buildFaqJsonLd(
    faqs.map(({ question, answer }) => ({ question, answer })),
    "/docs/faq",
  );
  const breadcrumbJsonLd = buildFaqJsonLd(
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
        Still have questions about private prediction markets, fixed ticket size, or settlement receipts?{" "}
        <Link href="/contact" className="text-brand-300 underline">
          Contact us
        </Link>
        .
      </p>
      <JsonLd data={faqSchema} id="faq-schema" />
      <JsonLd data={breadcrumbJsonLd} id="faq-schema-breadcrumb" />
      <DocsStructuredData slug="faq" />
    </>
  );
}
