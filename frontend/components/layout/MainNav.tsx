"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import type { Route } from "next";
import { ConnectWalletButton } from "@/components/wallet/ConnectWalletButton";
import { useFxStream } from "@/hooks/useFxStream";
import { FX_DEFAULT_PATH } from "@/lib/pricing-client";
import { PriceBanner } from "@/components/layout/PriceBanner";
import { resolveUrlConfig } from "@/lib/env-presets";
import { formatZenUsd } from "@/lib/fx";

const navLinks = [
  { href: "/markets/search", label: "Search" },
  { href: "/proofs", label: "Proofs" },
  { href: "/docs", label: "Docs" },
  { href: "/contact", label: "Contact" },
] as const;

const resolvedSiteUrl = (resolveUrlConfig().siteUrl ?? "").trim();
const fallbackHomeRoute: Route = "/";
const isTestEnv = (process.env.NODE_ENV ?? "").toLowerCase() === "test";
const rawHomeLink = isTestEnv ? "/" : resolvedSiteUrl;
const internalHomeHref: Route =
  rawHomeLink && rawHomeLink.startsWith("/") ? (rawHomeLink as Route) : fallbackHomeRoute;
const externalHomeHref = !isTestEnv && /^https?:\/\//.test(rawHomeLink) ? rawHomeLink : null;

/**
 * Top navigation with logo, menu links, and Connect Wallet CTA.
 * Sticks to the viewport top so users can access nav/actions while scrolling.
 */
export function MainNav() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const { fx, error: fxError, status } = useFxStream(FX_DEFAULT_PATH);
  const fxStale = status === "stale";
  const fxValue = formatZenUsd(fx?.zen_usd);
  const fxLabel = fxValue ? `ZEN/USD $${fxValue}` : null;

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
    <header className="sticky top-0 z-50 border-b border-white/10 bg-black/50 backdrop-blur-2xl">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
      <div className="absolute inset-y-0 right-8 hidden w-40 bg-brand-500/10 blur-3xl lg:block" aria-hidden="true" />
      <div className="relative mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4">
        {externalHomeHref ? (
          <a
            href={externalHomeHref}
            className="flex items-center gap-3 text-white transition hover:opacity-90 cursor-pointer select-none"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <Image
              src="/brand/reveal-logo-wordmark.svg"
              alt="Reveal Market"
              width={200}
              height={56}
              priority
              className="select-none"
              style={{ width: "200px", height: "auto" }}
              draggable={false}
            />
          </a>
        ) : (
          <Link
            href={internalHomeHref}
            className="flex items-center gap-3 text-white transition hover:opacity-90 cursor-pointer select-none"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <Image
              src="/brand/reveal-logo-wordmark.svg"
              alt="Reveal Market"
              width={200}
              height={56}
              priority
              className="select-none"
              style={{ width: "200px", height: "auto" }}
              draggable={false}
            />
          </Link>
        )}
        <nav className="hidden items-center gap-8 text-base font-semibold tracking-wide text-white/80 md:flex">
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
      <PriceBanner fxLabel={fxLabel} fxStale={fxStale} fxError={fxError} />
    </header>
  );
}
