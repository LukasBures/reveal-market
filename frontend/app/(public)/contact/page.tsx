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
      <div className="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-8 px-4 py-12 text-white box-border pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] sm:py-16">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Contact</p>
          <h1 className="text-3xl font-semibold text-white sm:text-4xl">Contact</h1>
        </div>
        <ContactForm siteKey={siteKey} />
      </div>
      <JsonLd data={breadcrumbs} id="contact-breadcrumbs" />
      <JsonLd data={contactSchema} id="contact-schema" />
    </>
  );
}
