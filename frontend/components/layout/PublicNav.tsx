/*
 * Lightweight navigation for public/marketing pages.
 * Avoids wallet providers, price streams, and other heavy client dependencies.
 */
"use client";

import Link from "next/link";
import Image from "next/image";
import { useState, useEffect, useRef } from "react";
import type { Route } from "next";
import { usePathname } from "next/navigation";

const navLinks: { href: Route; label: string }[] = [
  { href: "/search", label: "Search" },
  { href: "/docs", label: "Docs" },
  { href: "/contact", label: "Contact" },
  { href: "/proofs", label: "Receipts" },
];

export function PublicNav() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const firstLinkRef = useRef<HTMLAnchorElement | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    if (!isMobileMenuOpen) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsMobileMenuOpen(false);
        triggerRef.current?.focus();
      }
      if (event.key === "Tab") {
        const focusable = Array.from(
          document.querySelectorAll<HTMLElement>("#public-mobile-nav a, #public-mobile-nav button"),
        ).filter((el) => !el.hasAttribute("disabled"));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", handler);
    // Move focus to first nav link when opened
    firstLinkRef.current?.focus();
    return () => window.removeEventListener("keydown", handler);
  }, [isMobileMenuOpen]);

  const isLandingPage = pathname === "/";

  if (isLandingPage) {
    return (
      <header className="sticky top-0 z-40 border-b border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
        <div className="relative mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
          <Link
            href="/"
            className="flex flex-shrink-0 items-center gap-3 text-white transition hover:opacity-90 cursor-pointer select-none"
          >
            <Image
              src="/brand/reveal-logo-wordmark.svg"
              alt="Reveal Market"
              width={200}
              height={56}
              priority
              className="h-auto w-[160px] max-w-full select-none sm:w-[200px]"
            />
          </Link>
        <div className="flex items-center gap-2">
          <a
            href="https://x.com/RevealMarket"
            target="_blank"
            rel="noreferrer"
            className="hidden items-center justify-center gap-2 rounded-full bg-brand-500 px-4 py-2 text-xs font-semibold uppercase tracking-[0.35em] text-white transition hover:bg-brand-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-300 md:inline-flex"
          >
            Follow updates
          </a>
          <a
            href="https://x.com/RevealMarket"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center justify-center rounded-full border border-white/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.35em] text-white/80 transition hover:border-white hover:text-white md:hidden"
          >
            Follow
          </a>
        </div>
        </div>
      </header>
    );
  }

  return (
    <header
      className="sticky top-0 z-40 border-b border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
      data-testid="public-nav"
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
      <div className="relative mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-4">
        <Link
          href="/"
          className="flex flex-shrink-0 items-center gap-3 text-white transition hover:opacity-90 cursor-pointer select-none"
          onClick={() => setIsMobileMenuOpen(false)}
        >
          <Image
            src="/brand/reveal-logo-wordmark.svg"
            alt="Reveal Market"
            width={200}
            height={56}
            priority
            className="h-auto w-[160px] max-w-full select-none sm:w-[200px]"
          />
        </Link>
        <nav className="hidden flex-1 items-center justify-center gap-8 text-base font-semibold tracking-wide text-white/80 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-full px-3 py-1 transition hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-3 text-sm md:text-base">
          <a
            href="https://x.com/RevealMarket"
            target="_blank"
            rel="noreferrer"
            className="hidden items-center justify-center gap-2 rounded-full bg-brand-500 px-4 py-2 text-xs font-semibold uppercase tracking-[0.35em] text-white transition hover:bg-brand-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-300 md:inline-flex"
          >
            Follow updates
          </a>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold uppercase tracking-[0.4em] text-white/80 transition hover:border-white hover:text-white md:hidden"
            aria-expanded={isMobileMenuOpen}
            aria-controls="public-mobile-nav"
            onClick={() => setIsMobileMenuOpen((prev) => !prev)}
            ref={triggerRef}
          >
            Menu
            <span className="relative h-1.5 w-1.5 rounded-full bg-accent-400 shadow-[0_0_10px_rgba(123,240,94,0.8)]" />
          </button>
        </div>
      </div>
      {isMobileMenuOpen ? (
        <>
          <div className="relative z-40 md:hidden">
            <nav
              id="public-mobile-nav"
              className="mx-4 mb-4 rounded-2xl border border-white/10 bg-slate-950/90 p-4 text-sm text-white/90 shadow-[0_18px_40px_rgba(2,6,40,0.45)]"
            >
              <div className="flex flex-col gap-3">
                {navLinks.map((link, index) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="rounded-full border border-white/10 px-4 py-2 text-center font-semibold uppercase tracking-[0.25em] transition hover:border-white hover:text-white"
                    onClick={() => {
                      setIsMobileMenuOpen(false);
                      triggerRef.current?.focus();
                    }}
                    ref={index === 0 ? firstLinkRef : undefined}
                  >
                    {link.label}
                  </Link>
                ))}
              </div>
            </nav>
          </div>
          <div
            className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm md:hidden"
            onClick={() => setIsMobileMenuOpen(false)}
            aria-hidden="true"
          />
        </>
      ) : null}
    </header>
  );
}
