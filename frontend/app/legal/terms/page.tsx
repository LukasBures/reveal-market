import { buildMetadata } from "@/lib/seo";

export const metadata = buildMetadata({
  title: "Reveal Market Terms of Service",
  description: "Understand the legal terms governing access to the Reveal Market website and services.",
  path: "/legal/terms",
  keywords: ["terms", "legal", "service", "compliance"],
});

export default function TermsPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 text-slate-200">
      <h1 className="text-3xl font-semibold text-white">Terms of Service</h1>
      <p className="mt-4">
        These Terms govern your access to the Reveal Market website and related
        services. By accessing the site you agree to these terms.
      </p>
      <ol className="mt-8 space-y-4 list-decimal pl-6">
        <li>
          <strong>Eligibility.</strong> You must be legally permitted to use
          prediction markets in your jurisdiction.
        </li>
        <li>
          <strong>No warranties.</strong> Reveal Market provides software “as
          is” without warranties of any kind.
        </li>
        <li>
          <strong>Limitation of liability.</strong> We are not liable for any
          damages arising from use of the site or associated smart contracts.
        </li>
        <li>
          <strong>Changes.</strong> Terms may change at any time. Continued use
          constitutes acceptance of updates.
        </li>
      </ol>
      <p className="mt-8 text-sm text-slate-400">
        Last updated {new Date().getFullYear()}.
      </p>
    </div>
  );
}
