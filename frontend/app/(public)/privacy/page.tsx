import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Privacy Policy",
  description: "How Reveal Market collects, stores, and protects partner and visitor information.",
  path: "/privacy",
  keywords: ["privacy", "policy", "data protection"],
});

export default function PrivacyPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Privacy", path: "/privacy" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "Reveal Market Privacy Policy",
    description: "How Reveal Market collects, stores, and protects partner and visitor information.",
    path: "/privacy",
  });
  return (
    <>
      <div className="mx-auto max-w-3xl px-4 py-16 text-slate-200">
        <h1 className="text-3xl font-semibold text-white">Privacy Policy</h1>
        <p className="mt-4">
          Reveal Market respects your privacy. This policy explains what data we
          collect and how we use it.
        </p>
        <ul className="mt-8 space-y-4 list-disc pl-6">
          <li>
            <strong>Network data.</strong> We log anonymous request metadata
            (timestamp, route, response time) for debugging.
          </li>
          <li>
            <strong>Contact info.</strong> If you submit the contact form, we store your details only to respond to your
            request. We do not sell personal data.
          </li>
          <li>
            <strong>Cookies.</strong> The site may set functional cookies for
            session state. See our cookie policy for details.
          </li>
          <li>
            <strong>Third-party services.</strong> GitBook, Cloudflare, and other
            providers may have their own data policies.
          </li>
        </ul>
        <p className="mt-8">
          Questions? Use the{" "}
          <Link href="/contact" className="text-brand-300 underline">
            contact form
          </Link>{" "}
          and the team will respond directly.
        </p>
      </div>
      <JsonLd data={breadcrumbs} id="privacy-breadcrumbs" />
      <JsonLd data={articleSchema} id="privacy-article" />
    </>
  );
}
