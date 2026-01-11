import type { Metadata } from "next";
import { DocsStructuredData } from "@/components/docs/DocsStructuredData";
import { docsMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...docsMetadata("privacy-security"),
  description:
    "Privacy and security at Reveal Market: private commits and published settlement receipts for every resolved market.",
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
        why. Access uses passcodes during the MVP, and ops can pause or close boards when needed.
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
        Boards show status and pauses before you commit, reinforcing that private prediction markets remain transparent
        when it matters. Access gating keeps orderflow tight until receipts publish.
      </p>
      <p className="text-slate-200">
        For access questions, incident reports, or compliance needs, reach out via the{" "}
        <a href="/contact" className="text-brand-300 underline">
          contact form
        </a>
        .
      </p>
      <DocsStructuredData slug="privacy-security" />
    </>
  );
}
