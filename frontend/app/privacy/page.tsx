import { buildMetadata } from "@/lib/seo";

export const metadata = buildMetadata({
  title: "Reveal Market Privacy Policy",
  description: "How Reveal Market collects, stores, and protects partner and visitor information.",
  path: "/privacy",
  keywords: ["privacy", "policy", "data protection"],
});

export default function PrivacyPage() {
  return (
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
          <strong>Contact info.</strong> If you email us, we store your email to
          respond. We do not sell personal data.
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
        Questions? Contact{" "}
        <a
          href="mailto:hello@revealmarket.xyz"
          className="text-brand-300 underline"
        >
          hello@revealmarket.xyz
        </a>
        .
      </p>
    </div>
  );
}
