"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const navLinks = [
  { href: "/", label: "Markets" },
  { href: "/about", label: "About" },
  { href: "/docs", label: "Docs" },
];

export function MainNav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-white/10 bg-black/50 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <Link href="/" className="font-semibold tracking-tight text-lg">
          Reveal Market
        </Link>
        <nav className="flex items-center gap-6 text-sm font-medium">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={clsx(
                "transition-colors hover:text-brand-200",
                pathname === link.href ? "text-brand-200" : "text-slate-300"
              )}
            >
              {link.label}
            </Link>
          ))}
          <Link
            href="https://docs.revealmarket.xyz"
            className="rounded-full bg-brand-500 px-4 py-1 text-sm font-semibold text-white shadow-glow-brand transition hover:bg-brand-400"
          >
            View Docs
          </Link>
        </nav>
      </div>
    </header>
  );
}
