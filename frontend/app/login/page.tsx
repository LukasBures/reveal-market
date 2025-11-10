import Link from "next/link";
import type { Metadata } from "next";
import { buildMetadata } from "@/lib/seo";

export const metadata: Metadata = buildMetadata({
  title: "Log In | Reveal Market",
  description: "Wallet connect authentication is coming soon.",
  path: "/login",
  robots: {
    index: false,
    follow: false,
  },
});

export default function LoginPage() {
  return (
    <div className="min-h-[70vh] bg-gradient-to-b from-slate-950 via-black to-slate-950">
      <div className="mx-auto flex max-w-3xl flex-col items-center gap-6 px-4 py-24 text-center text-white">
        <p className="text-xs uppercase tracking-[0.35em] text-slate-500">Wallet Connect</p>
        <h1 className="text-4xl font-semibold">Log In experience coming soon</h1>
        <p className="text-slate-300">
          We&apos;re finalizing wallet-connect login flows. In the meantime, feel free to review open markets,
          docs, and legal disclosures.
        </p>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Link
            href="/"
            className="rounded-full border border-white/40 px-8 py-3 font-semibold text-white transition hover:bg-white/10"
          >
            Browse Markets
          </Link>
          <Link
            href="/docs"
            className="rounded-full border border-white/40 px-8 py-3 font-semibold text-white transition hover:bg-white/10"
          >
            View Docs
          </Link>
        </div>
      </div>
    </div>
  );
}
