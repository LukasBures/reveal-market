import type { Metadata } from "next";
import Link from "next/link";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = docsMetadata("api");

export default function ApiReferencePage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
        Partners · Data
      </p>
      <h1 className="text-3xl font-semibold text-white">Data & API Access</h1>
      <p>
        Institutional clients plug into Reveal via high-availability REST endpoints,
        WebSocket streams, and optional snapshots. Rather than expose technical
        minutiae, here is what matters:
      </p>
      <ul className="mt-4 list-disc space-y-3 pl-6 text-slate-200">
        <li>
          <strong>Real-time markets.</strong> Filtered feeds by status, category,
          liquidity tier, or geography.
        </li>
        <li>
          <strong>Settlement archives.</strong> Immutable resolution history for
          audit and valuation models.
        </li>
        <li>
          <strong>Partner controls.</strong> Rate limits, authentication, and
          dedicated endpoints tailored per liquidity provider or exchange.
        </li>
      </ul>
      <p className="mt-6">
        API keys are granted to verified partners under commercial terms. Use the{" "}
        <Link href="/contact" className="text-brand-300 underline">
          contact form
        </Link>{" "}
        to begin due diligence.
      </p>
      <DocsStructuredData slug="api" />
    </>
  );
}
