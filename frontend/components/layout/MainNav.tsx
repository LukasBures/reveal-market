"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import type { Route } from "next";
import { usePathname } from "next/navigation";
import { ConnectWalletButton } from "@/components/wallet/ConnectWalletButton";
import { useFxStream } from "@/hooks/useFxStream";
import { FX_DEFAULT_PATH } from "@/lib/pricing-client";
import { PriceBanner } from "@/components/layout/PriceBanner";
import { resolveUrlConfig } from "@/lib/env-presets";
import { formatZenUsd } from "@/lib/fx";

type MainNavProps = {
  initialHasAccess?: boolean;
  gateEnabled?: boolean;
};

const resolvedUrls = resolveUrlConfig();
const resolvedSiteUrl = (resolvedUrls.siteUrl ?? "").trim();
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
export function MainNav({ initialHasAccess = false, gateEnabled = false }: MainNavProps) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [apiWarning, setApiWarning] = useState<string | null>(null);
  const [streamerWarning, setStreamerWarning] = useState<string | null>(null);
  const pathname = usePathname();
  const { fx, error: fxError, status } = useFxStream(FX_DEFAULT_PATH);
  const fxStale = status === "stale";
  const fxValue = formatZenUsd(fx?.zen_usd);
  const fxLabel = fxValue ? `ZEN/USD $${fxValue}` : null;
  const warningsEnabled = (() => {
    const env = (process.env.NODE_ENV ?? "").toLowerCase();
    if (env === "production" || env === "test") return false;
    if ((process.env.VITEST ?? "").toLowerCase() === "true") return false;
    return true;
  })();

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

  useEffect(() => {
    if (!warningsEnabled) return;
    if (typeof window === "undefined" || typeof fetch !== "function") return;
    let cancelled = false;
    const pageProtocol = window.location?.protocol ?? "http:";

    const isMixedContent = (baseUrl: string) => {
      try {
        const parsed = new URL(baseUrl);
        const protocol = parsed.protocol;
        return pageProtocol === "https:" && (protocol === "http:" || protocol === "ws:");
      } catch {
        return false;
      }
    };

    const checkOrigin = async (label: string, baseUrl: string, path: string) => {
      if (!baseUrl) return `${label} origin missing`;
      if (isMixedContent(baseUrl)) return `${label} blocked (mixed content)`;
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 3000);
      try {
        const url = `${baseUrl.replace(/\/$/, "")}${path}`;
        const response = await fetch(url, { cache: "no-store", signal: controller.signal });
        if (!response.ok) {
          return `${label} unreachable`;
        }
        return null;
      } catch {
        return `${label} blocked/unreachable`;
      } finally {
        window.clearTimeout(timeout);
      }
    };

    const run = async () => {
      const [apiWarningNext, streamerWarningNext] = await Promise.all([
        checkOrigin("API", resolvedUrls.apiBaseUrl, "/healthz"),
        checkOrigin("Streamer", resolvedUrls.streamerPublic, "/healthz"),
      ]);
      if (cancelled) return;
      setApiWarning(apiWarningNext);
      setStreamerWarning(streamerWarningNext);
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [warningsEnabled]);

  const isLanding = pathname === "/";
  const hasAccess = gateEnabled ? Boolean(initialHasAccess) : true;

  const showLandingMinimal = gateEnabled && isLanding && !hasAccess;
  if (showLandingMinimal) {
    return (
      <header className="sticky top-0 z-50 border-b border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
        <div className="relative mx-auto flex max-w-7xl items-center justify-between px-4 py-4">
          <Link
            href="/"
            className="flex flex-shrink-0 items-center gap-3 text-white transition hover:opacity-90 cursor-pointer select-none"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <div className="relative aspect-[25/7] w-[160px] sm:w-[200px]">
              <Image
                src="/brand/reveal-logo-wordmark.svg"
                alt="Reveal Market"
                fill
                sizes="(min-width: 640px) 200px, 160px"
                priority
                className="select-none object-contain"
              />
            </div>
          </Link>
          <div className="flex items-center gap-2">
            <a
              href="https://x.com/RevealMarket"
              target="_blank"
              rel="noreferrer"
              className="hidden items-center justify-center gap-2 rounded-full bg-brand-500 px-4 py-2 text-xs font-semibold uppercase tracking-[0.35em] text-white transition hover:bg-brand-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-300 md:inline-flex"
            >
              Request access
            </a>
            <a
              href="https://x.com/RevealMarket"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center justify-center rounded-full border border-white/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.35em] text-white/80 transition hover:border-white hover:text-white md:hidden"
            >
              Request
            </a>
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="sticky top-0 z-50 border-b border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
      <div className="relative mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-4" data-testid="main-nav">
        {externalHomeHref ? (
          <a
            href={externalHomeHref}
            className="flex flex-shrink-0 items-center gap-3 text-white transition hover:opacity-90 cursor-pointer select-none"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <div className="relative aspect-[25/7] w-[160px] sm:w-[200px]">
              <Image
                src="/brand/reveal-logo-wordmark.svg"
                alt="Reveal Market"
                fill
                sizes="(min-width: 640px) 200px, 160px"
                priority
                className="select-none object-contain"
              />
            </div>
          </a>
        ) : (
          <Link
            href={internalHomeHref}
            className="flex flex-shrink-0 items-center gap-3 text-white transition hover:opacity-90 cursor-pointer select-none"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            <div className="relative aspect-[25/7] w-[160px] sm:w-[200px]">
              <Image
                src="/brand/reveal-logo-wordmark.svg"
                alt="Reveal Market"
                fill
                sizes="(min-width: 640px) 200px, 160px"
                priority
                className="select-none object-contain"
              />
            </div>
          </Link>
        )}
        <nav className="hidden flex-1 items-center justify-center gap-8 text-base font-semibold tracking-wide text-white/80 md:flex">
          <Link
            href="/search"
            className="rounded-full px-3 py-1 transition hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          >
            Search
          </Link>
          <Link
            href="/proofs"
            className="rounded-full px-3 py-1 transition hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          >
            Proofs
          </Link>
          <Link
            href="/dashboard"
            className="rounded-full px-3 py-1 transition hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
          >
            Dashboard
          </Link>
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
                <Link
                  href="/search"
                  className="rounded-full border border-white/10 px-4 py-2 text-center font-semibold uppercase tracking-[0.25em] transition hover:border-white hover:text-white"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Search
                </Link>
                <Link
                  href="/proofs"
                  className="rounded-full border border-white/10 px-4 py-2 text-center font-semibold uppercase tracking-[0.25em] transition hover:border-white hover:text-white"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Proofs
                </Link>
                <Link
                  href="/dashboard"
                  className="rounded-full border border-white/10 px-4 py-2 text-center font-semibold uppercase tracking-[0.25em] transition hover:border-white hover:text-white"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Dashboard
                </Link>
              </nav>
            </div>
          </div>
          <div className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden" onClick={() => setIsMobileMenuOpen(false)} />
        </>
      ) : null}
      <PriceBanner
        fxLabel={fxLabel}
        fxStale={fxStale}
        fxError={fxError}
        apiWarning={apiWarning}
        streamerWarning={streamerWarning}
      />
    </header>
  );
}
