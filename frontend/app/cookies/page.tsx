import type { Metadata } from "next";
import Link from "next/link";
import { buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Cookie Policy",
  description: "Transparency about tracking technologies used across Reveal Market properties.",
  path: "/cookies",
  keywords: ["cookies", "policy", "tracking"],
});

export default function CookiesPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16 text-slate-200">
      <h1 className="text-3xl font-semibold text-white">Cookie Policy</h1>
      <p className="mt-4">
        Reveal Market uses cookies to improve the browsing experience. By using
        the site you consent to these cookies.
      </p>
      <ul className="mt-8 space-y-4 list-disc pl-6">
        <li>
          <strong>Essential cookies.</strong> Required for basic site
          functionality (session state, preferences).
        </li>
        <li>
          <strong>Analytics cookies.</strong> Aggregate metrics (page views,
          latency) help us improve the site; data is anonymized.
        </li>
        <li>
          <strong>Third-party cookies.</strong> Embedded docs (GitBook) or CDN
          providers may set their own cookies.
        </li>
      </ul>
      <p className="mt-8">
        You can disable cookies in your browser settings, but some features may
        stop working. Questions? Use the{" "}
        <Link href="/contact" className="text-brand-300 underline">
          contact form
        </Link>
        .
      </p>
    </div>
  );
}
