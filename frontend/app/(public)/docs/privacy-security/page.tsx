import Link from "next/link";
import type { Metadata } from "next";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("privacy-security"),
  description:
    "Reveal Market keeps participation private during live markets and publishes settlement receipts after resolution so outcomes and payouts stay transparent.",
  keywords: [
    "private commits",
    "settlement receipts",
    "fixed ticket size",
    "claims",
  ],
};

export default function PrivacySecurityPage() {
  return (
    <>
      <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Privacy & Security</p>
      <h1 className="text-4xl font-semibold text-white">Privacy & Security</h1>
      <p className="text-lg text-slate-300">
        Markets stay private while they&apos;re live. When they settle, we publish receipts so you can see what won and
        why. Access uses passcodes during the MVP, and markets can be paused or closed when needed.
      </p>
      <ul className="list-disc space-y-3 pl-6 text-slate-200">
        <li>
          <strong>Private commits.</strong> Tickets are committed without broadcasting orderflow; receipts surface after
          results are final.
        </li>
        <li>
          <strong>Clear receipts.</strong> Every settled market includes a published summary of the outcome and payouts,
          reinforcing trust in each prediction market.
        </li>
        <li>
          <strong>Operational controls.</strong> Access uses passcodes during the MVP; markets can be paused or closed,
          and status is visible to users before they commit.
        </li>
      </ul>
      <p className="text-slate-200">
        Markets show status and pause states before you commit, keeping things transparent when it matters. Access
        controls keep order flow private until receipts publish.
      </p>
      <p className="text-slate-200">
        For access questions, incident reports, or compliance needs, reach out via the{" "}
        <Link href="/contact" className="text-brand-300 underline">
          contact form
        </Link>
        .
      </p>
      <DocsStructuredData slug="privacy-security" />
    </>
  );
}
