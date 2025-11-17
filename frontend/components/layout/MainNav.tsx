"use client";

import Image from "next/image";
import Link from "next/link";
import { ConnectWalletButton } from "@/components/wallet/ConnectWalletButton";

const navLinks = [
  { href: "/about", label: "About" },
  { href: "/proofs", label: "Proofs" },
  { href: "/docs", label: "Docs" },
] as const;

export function MainNav() {
  return (
    <header className="relative border-b border-white/10 bg-black/40 backdrop-blur-2xl">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
      <div className="absolute inset-y-0 right-8 hidden w-40 bg-brand-500/10 blur-3xl lg:block" aria-hidden="true" />
      <div className="relative mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4">
        <Link href="/" className="flex items-center gap-3 text-white transition hover:opacity-90">
          <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-white/15 bg-gradient-to-br from-brand-500/40 to-brand-700/40 shadow-glow-brand">
            <Image src="/brand/reveal-mark.svg" alt="Reveal Market mark" width={34} height={54} priority />
          </span>
          <span>
            <span className="font-display text-base uppercase tracking-[0.3em]">Reveal Market</span>
            <span className="block text-xs font-semibold text-white/60">zk commit &amp; reveal venue</span>
          </span>
        </Link>
        <nav className="hidden items-center gap-6 text-sm text-white/70 md:flex">
          {navLinks.map((link) => (
            <Link key={link.href} href={link.href} className="transition hover:text-white">
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Link
            href="/docs"
            className="hidden rounded-full border border-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-[0.3em] text-white/80 transition hover:border-white/40 hover:text-white sm:inline-flex"
          >
            Docs
          </Link>
          <ConnectWalletButton />
        </div>
      </div>
    </header>
  );
}
