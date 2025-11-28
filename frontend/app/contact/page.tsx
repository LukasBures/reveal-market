import type { Metadata } from "next";
import { ContactForm } from "@/components/contact/ContactForm";
import { buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Contact Reveal Market",
  description: "Share your use case or diligence needs and the Reveal Market team will follow up.",
  path: "/contact",
  keywords: ["contact", "partnerships", "markets", "Reveal Market"],
});

export default function ContactPage() {
  const siteKey = process.env.CONTACT_TURNSTILE_SITE_KEY ?? "";
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-10 text-white">
      <div className="space-y-3">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-400">Contact</p>
        <h1 className="text-3xl font-semibold">Talk with the team</h1>
        <p className="text-slate-200 leading-relaxed">
          Share how you plan to use Reveal Market—whether that is spinning up a branded marketplace, integrating the API,
          or reviewing operational controls. We will route your note to the right owner and respond quickly.
        </p>
      </div>
      <ContactForm siteKey={siteKey} />
      <div className="rounded-2xl border border-white/10 bg-black/40 p-4 text-sm text-slate-200">
        <p className="font-semibold text-white">What happens next?</p>
        <ul className="mt-2 space-y-1 text-slate-300">
          <li>• We log your message securely and reply from the ops desk.</li>
          <li>• No marketing blasts—only a direct response relevant to your request.</li>
          <li>• For status updates any time, check the public docs and roadmap.</li>
        </ul>
      </div>
    </div>
  );
}
