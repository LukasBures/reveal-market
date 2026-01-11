import type { Metadata } from "next";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Terms of Service",
  description: "Understand the legal terms governing access to the Reveal Market website and services.",
  path: "/terms",
  keywords: ["terms", "legal", "service", "compliance"],
});

export default function TermsPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Terms", path: "/terms" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "Reveal Market Terms of Service",
    description: "Understand the legal terms governing access to the Reveal Market website and services.",
    path: "/terms",
  });
  return (
    <>
      <div className="mx-auto max-w-7xl px-4 py-16 text-slate-200 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Legal</p>
        <h1 className="text-4xl font-semibold text-white">Terms of Service</h1>
        <p className="mt-4 text-lg text-slate-300">
          These Terms govern your access to the Reveal Market website and related services. By accessing the site you agree
          to these terms.
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
      <JsonLd data={breadcrumbs} id="terms-breadcrumbs" />
      <JsonLd data={articleSchema} id="terms-article" />
    </>
  );
}
