import Link from "next/link";

const footerLinks = [
  { href: "/about", label: "About" } as const,
  { href: "/docs", label: "Docs" } as const,
  { href: "/proofs", label: "Proofs" } as const,
  { href: "/legal", label: "Legal Center" } as const,
];

export function Footer() {
  return (
    <footer className="border-t border-white/10 bg-slate-950/80">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm text-slate-400 md:flex-row md:items-center md:justify-between">
        <p>© {new Date().getFullYear()} Reveal Market. All rights reserved.</p>
        <div className="flex flex-wrap items-center gap-4">
          {footerLinks.map((link) => (
            <Link key={link.href} href={link.href} className="hover:text-white">
              {link.label}
            </Link>
          ))}
          <Link href="https://x.com/RevealMarket" className="hover:text-white" rel="noreferrer" target="_blank">
            X / Twitter
          </Link>
          <Link href="mailto:hello@revealmarket.xyz" className="hover:text-white">
            Contact
          </Link>
        </div>
      </div>
    </footer>
  );
}
