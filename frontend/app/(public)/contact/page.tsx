import type { Metadata } from "next";
import { ContactForm } from "@/components/contact/ContactForm";
import { JsonLd } from "@/components/seo/JsonLd";
import { buildBreadcrumbJsonLd, buildContactPageJsonLd, buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Contact Reveal Market",
  description:
    "Contact Reveal Market for support or questions about private prediction markets, fixed tickets, and settlement receipts.",
  path: "/contact",
  keywords: [
    "contact Reveal Market",
    "private prediction markets",
    "fixed ticket size",
    "settlement receipts",
    "support",
  ],
});

export default function ContactPage() {
  const siteKey = process.env.CONTACT_TURNSTILE_SITE_KEY ?? "";
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Contact", path: "/contact" },
  ]);
  const contactSchema = buildContactPageJsonLd("/contact");
  return (
    <>
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-16 text-white pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Contact</p>
          <h1 className="text-4xl font-semibold text-white">Talk with the team</h1>
          <p className="text-lg text-slate-300 leading-relaxed">
            Share how you plan to use Reveal Market—whether that&apos;s trading, access for your desk, or a simple status
            check. We&apos;ll route your note to the right owner and respond quickly.
          </p>
        </div>
        <ContactForm siteKey={siteKey} />
        <div className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-slate-200">
          <p className="font-semibold text-white">What happens next?</p>
          <ul className="mt-2 space-y-1 text-slate-300">
            <li>• We log your message securely and reply from the ops desk.</li>
            <li>• No marketing blasts—only a direct response relevant to your request.</li>
            <li>• For status updates any time, check the public docs or status link in the footer.</li>
            <li>• Share your wallet (optional) and use case so we can respond faster.</li>
          </ul>
          <p className="mt-3 text-slate-300">We typically respond quickly during trading hours.</p>
        </div>
      </div>
      <JsonLd data={breadcrumbs} id="contact-breadcrumbs" />
      <JsonLd data={contactSchema} id="contact-schema" />
    </>
  );
}
