import type { Metadata } from "next";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildArticleJsonLd, buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Reveal Market Terms of Service",
  description:
    "Terms governing access to the Reveal Market website, software, and related services, including eligibility, acceptable use, and risk disclosures.",
  path: "/terms",
  keywords: ["terms", "legal", "acceptable use", "risk disclosure", "web3"],
  type: "article",
});

export default function TermsPage() {
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Terms", path: "/terms" },
  ]);
  const articleSchema = buildArticleJsonLd({
    title: "Reveal Market Terms of Service",
    description:
      "Terms governing access to the Reveal Market website, software, and related services, including eligibility, acceptable use, and risk disclosures.",
    path: "/terms",
    dateModified: "2026-02-18",
  });
  return (
    <>
      <div className="mx-auto max-w-7xl px-4 py-12 text-slate-200 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Legal</p>
        <h1 className="text-3xl font-semibold text-white sm:text-4xl">Terms of Service</h1>
        <p className="mt-4 text-base text-slate-300 sm:text-lg">
          These Terms govern your access to the Reveal Market website, interfaces, documentation, and related services.
          By accessing or using any part of the site, you agree to be bound by these Terms.
        </p>
        <ol className="mt-8 space-y-6 list-decimal pl-6">
          <li>
            <strong>Eligibility and compliance.</strong> You are responsible for determining whether you are legally
            permitted to access or use prediction markets, blockchain services, or related tools. You agree not to use
            the services where prohibited, restricted, or licensed.
          </li>
          <li>
            <strong>Acceptable use.</strong> You agree not to misuse the services, including attempting to interfere
            with availability, access data you are not authorized to access, or use the services for unlawful, abusive,
            or deceptive purposes.
          </li>
          <li>
            <strong>No custody; user control.</strong> Reveal Market does not custody funds or assets. You interact with
            third-party wallets, networks, or smart contracts at your own risk and are responsible for safeguarding your
            keys, credentials, and devices.
          </li>
          <li>
            <strong>Risk disclosures.</strong> Prediction markets, digital assets, and smart contracts are experimental
            and may be volatile, illiquid, or unavailable. Smart contracts can fail or behave unexpectedly. You assume
            all risks of using the services.
          </li>
          <li>
            <strong>No warranties.</strong> The services are provided “as is” and “as available” without warranties of
            any kind, whether express or implied, including fitness for a particular purpose, non-infringement, or
            availability.
          </li>
          <li>
            <strong>Limitation of liability.</strong> To the maximum extent permitted by law, Reveal Market is not liable
            for any indirect, incidental, special, consequential, or punitive damages, or any loss of profits, data, or
            goodwill, arising from your use of the services.
          </li>
          <li>
            <strong>Third-party services.</strong> The services may link to or depend on third-party providers. We are not
            responsible for their content, availability, or conduct. Your use of third-party services is governed by
            their terms and policies.
          </li>
          <li>
            <strong>Changes to services or terms.</strong> We may modify, suspend, or discontinue any part of the
            services, and update these Terms from time to time. Continued use after changes become effective constitutes
            acceptance of the updated Terms.
          </li>
        </ol>
        <p className="mt-8 text-sm text-slate-400">
          Last updated February 18, 2026.
        </p>
      </div>
      <JsonLd data={breadcrumbs} id="terms-breadcrumbs" />
      <JsonLd data={articleSchema} id="terms-article" />
    </>
  );
}
