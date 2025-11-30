import Link from "next/link";
import Image from "next/image";

const footerLinks = [
  { href: "/about", label: "About" } as const,
  { href: "/docs", label: "Docs" } as const,
  { href: "/proofs", label: "Proofs" } as const,
  { href: "/legal", label: "Legal Center" } as const,
  { href: "/contact", label: "Contact" } as const,
];

export function Footer() {
  return (
    <footer className="border-t border-white/10 bg-black/50 backdrop-blur-2xl">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-12 text-sm text-slate-300 md:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-4">
          <Link href="/" className="inline-flex items-center gap-3 text-white">
            <Image
              src="/brand/reveal-logo-wordmark.svg"
              alt="Reveal Market logo"
              width={240}
              height={64}
              priority
              className="h-auto w-[240px]"
            />
          </Link>
          <p className="text-base text-slate-200">
            Institutional-grade prediction markets with Horizen roots, zk-settled proofs, and provable custody.
          </p>
          <div className="wolf-aura flex items-center gap-4 rounded-2xl border border-white/10 p-4 text-left text-white">
            <img
              src="/brand/reveal-wolf-01.png"
              alt="Reveal Market wolf"
              className="h-16 w-16 rounded-2xl border border-white/15 bg-white/5 p-2"
              loading="lazy"
            />
            <div>
              <p className="text-xs uppercase tracking-[0.35em] text-white/70">Signal wolfpack</p>
              <p className="font-semibold text-white">Always-on risk ops &amp; zk attestations</p>
            </div>
          </div>
        </div>
        <div className="flex flex-col gap-5 md:items-end">
          <div className="flex flex-wrap gap-4 text-sm text-white/70 md:justify-end">
            {footerLinks.map((link) => (
              <Link key={link.href} href={link.href} className="transition hover:text-white">
                {link.label}
              </Link>
            ))}
            <Link
              href="https://x.com/RevealMarket"
              className="transition hover:text-white"
              rel="noreferrer"
              target="_blank"
            >
              X / Twitter
            </Link>
          </div>
          <p className="text-xs text-white/40">© {new Date().getFullYear()} Reveal Market. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
