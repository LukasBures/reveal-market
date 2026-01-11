import Link from "next/link";
import Image from "next/image";

const footerLinks = [
  { href: "/docs", label: "Docs" } as const,
  { href: "/legal", label: "Legal" } as const,
  { href: "/contact", label: "Contact" } as const,
];

export function Footer() {
  return (
    <footer className="border-t border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-12 text-sm text-slate-300 md:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-4">
          <Link href="/" className="inline-flex items-center gap-3 text-white">
            <div className="relative aspect-[15/4] w-[240px] max-w-full">
              <Image
                src="/brand/reveal-logo-wordmark.svg"
                alt="Reveal Market logo"
                fill
                sizes="240px"
                className="select-none object-contain"
                loading="lazy"
              />
            </div>
          </Link>
          <p className="text-base text-slate-200">Private while live, provable at the end.</p>
        </div>
        <div className="flex flex-col gap-5 md:items-end">
          <div className="flex flex-wrap gap-4 text-sm text-white/70 md:justify-end">
            {footerLinks.map((link) => (
              <Link key={link.href} href={link.href} className="py-1 transition hover:text-white">
                {link.label}
              </Link>
            ))}
            <a
              href="https://x.com/RevealMarket"
              target="_blank"
              rel="noreferrer"
              aria-label="Reveal Market on X"
              className="inline-flex items-center py-1 transition hover:text-white"
            >
              X
            </a>
          </div>
          <p className="text-xs text-white/40">© {new Date().getFullYear()} Reveal Market. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
