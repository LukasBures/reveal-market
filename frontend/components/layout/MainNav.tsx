"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import type { Route } from "next";
import { ConnectWalletButton } from "@/components/wallet/ConnectWalletButton";

const navLinks = [
  { href: "/about", label: "About" },
  { href: "/proofs", label: "Proofs" },
  { href: "/docs", label: "Docs" },
] as const;

const rawHomeLink = (process.env.NEXT_PUBLIC_SITE_URL ?? "").trim();
const fallbackHomeRoute: Route = "/";
const internalHomeHref: Route = rawHomeLink && rawHomeLink.startsWith("/")
  ? (rawHomeLink as Route)
  : fallbackHomeRoute;
const externalHomeHref = /^https?:\/\//.test(rawHomeLink) ? rawHomeLink : null;

export function MainNav() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  useEffect(() => {
    if (!isMobileMenuOpen) {
      return;
    }
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsMobileMenuOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isMobileMenuOpen]);

  return (
    <header className="relative border-b border-white/10 bg-black/50 backdrop-blur-2xl">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
      <div className="absolute inset-y-0 right-8 hidden w-40 bg-brand-500/10 blur-3xl lg:block" aria-hidden="true" />
      <div className="relative mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-4">
        {externalHomeHref ? (
          <a
            href={externalHomeHref}
            className="flex items-center gap-3 text-white transition hover:opacity-90"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <Image src="/brand/reveal-logo-wordmark.svg" alt="Reveal Market" width={200} height={56} priority className="h-10 w-auto" />
          </a>
        ) : (
          <Link
            href={internalHomeHref}
            className="flex items-center gap-3 text-white transition hover:opacity-90"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <Image src="/brand/reveal-logo-wordmark.svg" alt="Reveal Market" width={200} height={56} priority className="h-10 w-auto" />
          </Link>
        )}
        <nav className="hidden items-center gap-6 text-sm text-white/70 md:flex">
          {navLinks.map((link) => (
            <Link key={link.href} href={link.href} className="transition hover:text-white">
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold uppercase tracking-[0.4em] text-white/80 transition hover:border-white hover:text-white md:hidden"
            aria-expanded={isMobileMenuOpen}
            aria-label={isMobileMenuOpen ? "Close navigation" : "Open navigation"}
            onClick={() => setIsMobileMenuOpen((prev) => !prev)}
          >
            Menu
            <span className="relative h-1.5 w-1.5 rounded-full bg-accent-400 shadow-[0_0_10px_rgba(123,240,94,0.8)]" />
          </button>
          <div className="drop-shadow-[0_0_25px_rgba(123,240,94,0.45)]">
            <ConnectWalletButton />
          </div>
        </div>
      </div>
      {isMobileMenuOpen ? (
        <>
          <div className="md:hidden">
            <div className="mx-4 mb-4 rounded-2xl border border-white/10 bg-black/80 p-4 text-sm text-white/80">
              <nav className="flex flex-col gap-3">
                {navLinks.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="rounded-full border border-white/10 px-4 py-2 text-center font-semibold uppercase tracking-[0.25em] transition hover:border-white hover:text-white"
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    {link.label}
                  </Link>
                ))}
              </nav>
            </div>
          </div>
          <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden" onClick={() => setIsMobileMenuOpen(false)} />
        </>
      ) : null}
    </header>
  );
}
