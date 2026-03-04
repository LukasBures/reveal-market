"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import dynamic from "next/dynamic";
import type { Route } from "next";
import { usePathname, useSearchParams } from "next/navigation";

import { HeroSearch } from "@/components/marketing/HeroSearch";
import { resolveUrlConfig } from "@/lib/env-presets";
import { categorySlugFromLabel, parseCategorySlug } from "@/lib/slugs";

const ConnectWalletButton = dynamic(
  () =>
    import("@/components/wallet/ConnectWalletButton").then((m) => ({
      default: m.ConnectWalletButton,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="h-9 w-24 animate-pulse rounded-full bg-white/10" />
    ),
  }
);

const resolvedUrls = resolveUrlConfig();
const resolvedSiteUrl = (resolvedUrls.siteUrl ?? "").trim();
const fallbackHomeRoute: Route = "/";
const isTestEnv = (process.env.NODE_ENV ?? "").toLowerCase() === "test";
const rawHomeLink = isTestEnv ? "/" : resolvedSiteUrl;
const internalHomeHref: Route =
  rawHomeLink && rawHomeLink.startsWith("/") ? (rawHomeLink as Route) : fallbackHomeRoute;
const externalHomeHref = !isTestEnv && /^https?:\/\//.test(rawHomeLink) ? rawHomeLink : null;
const HERO_CATEGORY_FILTERS = ["All", "Crypto", "Finance", "Economy", "Sports", "Politics", "Geopolitics"];

/**
 * Top navigation with logo, menu links, and Connect Wallet CTA.
 * Sticks to the viewport top so users can access nav/actions while scrolling.
 */
export function MainNav() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const pathname = usePathname();
  const isLandingPage = pathname === "/";
  const isCategoryPage = /^\/[a-z][a-z0-9-]*$/.test(pathname) && parseCategorySlug(pathname.slice(1)) !== null;
  const showFiltersBar = isLandingPage || isCategoryPage;
  const headerHeightClass = showFiltersBar ? "h-[120px]" : "h-[72px]";
  const spacerClass = showFiltersBar ? "h-[120px]" : "h-[72px] bg-[#010314]";

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
    <>
      <header
        className={`fixed top-0 left-0 right-0 z-50 border-b border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] ${headerHeightClass}`}
      >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[72px] bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
      {showFiltersBar ? (
        <div className="pointer-events-none absolute inset-x-0 top-[72px] h-[48px] bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
      ) : null}
      <div
        className="relative mx-auto flex h-[72px] max-w-7xl flex-wrap items-center gap-4 px-4"
        data-testid="main-nav"
      >
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
        <nav className="hidden flex-1 items-center justify-center gap-6 text-base font-semibold tracking-wide text-white/80 md:flex">
          <div className="w-72 sm:w-80">
            <HeroSearch
              showButton={false}
              showIcon
              placeholder="Search"
              className="ml-auto w-20 transition-[width] duration-200 ease-out focus-within:w-full"
              containerClassName="px-3 py-2"
              inputClassName="text-sm placeholder:text-white/40"
            />
          </div>
          <Link
            href="/proofs"
            className={`rounded-full px-3 py-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 ${
              pathname === "/proofs"
                ? "bg-white/10 text-white"
                : "hover:bg-white/10 hover:text-white"
            }`}
          >
            Proofs
          </Link>
          <Link
            href="/dashboard"
            className={`rounded-full px-3 py-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 ${
              pathname === "/dashboard"
                ? "bg-white/10 text-white"
                : "hover:bg-white/10 hover:text-white"
            }`}
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
      {showFiltersBar ? (
        <Suspense fallback={null}>
          <HomeFiltersBar />
        </Suspense>
      ) : null}
      {isMobileMenuOpen ? (
        <>
          <div className="relative z-50 md:hidden">
            <div className="mx-4 mb-4 rounded-2xl border border-white/10 bg-slate-950/90 p-4 text-sm text-white/90 shadow-[0_18px_40px_rgba(2,6,40,0.45)]">
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
                  className={`rounded-full border px-4 py-2 text-center font-semibold uppercase tracking-[0.25em] transition ${
                    pathname === "/proofs"
                      ? "border-white text-white"
                      : "border-white/10 hover:border-white hover:text-white"
                  }`}
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Proofs
                </Link>
                <Link
                  href="/dashboard"
                  className={`rounded-full border px-4 py-2 text-center font-semibold uppercase tracking-[0.25em] transition ${
                    pathname === "/dashboard"
                      ? "border-white text-white"
                      : "border-white/10 hover:border-white hover:text-white"
                  }`}
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
      </header>
      {/* Offset page content for the fixed header. */}
      <div className={spacerClass} aria-hidden="true" />
    </>
  );
}

function HomeFiltersBar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const rawSortParam = searchParams.get("sort");
  const sortBy = (() => {
    if (rawSortParam === "newest") return "recent";
    if (rawSortParam === "trending") return "popularity";
    return "totalVolume";
  })();

  // Detect active category from pathname (e.g., /geopolitics → "geopolitics")
  const pathSegment = pathname === "/" ? null : pathname.slice(1);
  const activeCategory = pathSegment ? parseCategorySlug(pathSegment) : null;
  const isHome = pathname === "/";
  const hasActiveFilters = Boolean(activeCategory) || rawSortParam !== null;

  // Build the base path for sort links (stays on current category page)
  const basePath = activeCategory ? `/${activeCategory.slug}` : "/";

  return (
    <div className="border-t border-white/5 bg-black/80 text-xs text-white/80 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-2 sm:h-[48px] sm:flex-row sm:items-center sm:py-0">
        <div className="flex w-full flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <div className="relative flex-1">
            <div className="pointer-events-none absolute left-0 top-0 h-full w-10 bg-gradient-to-r from-black/80 to-transparent opacity-90" />
            <div className="pointer-events-none absolute right-0 top-0 h-full w-10 bg-gradient-to-l from-black/80 to-transparent opacity-90" />
            <div className="no-scrollbar flex snap-x snap-mandatory gap-2 overflow-x-auto pr-6">
              {HERO_CATEGORY_FILTERS.map((category) => {
                const isAll = category.toLowerCase() === "all";
                const slug =
                  categorySlugFromLabel(category) ?? category.toLowerCase().replace(/[^a-z0-9-]/g, "-");
                const isActive = isAll ? isHome : activeCategory?.slug === slug;
                const href = (isAll ? "/" : `/${slug}`) as Route;
                return (
                  <Link
                    key={category}
                    href={href}
                    className={`relative snap-start rounded-full border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.25em] transition sm:py-1 ${
                      isActive
                        ? "border-brand-400/80 bg-brand-400/20 text-white"
                        : "border-white/10 bg-white/5 text-white/80 hover:border-brand-400/60 hover:text-white hover:bg-white/10"
                    }`}
                  >
                    <span className="relative">{category}</span>
                  </Link>
                );
              })}
            </div>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            {[
              { label: "Trending", value: "trending", active: sortBy === "popularity" },
              { label: "Volume", value: "volume", active: sortBy === "totalVolume" },
              { label: "Newest", value: "newest", active: sortBy === "recent" },
            ].map((pill) => {
              const params = new URLSearchParams();
              if (pill.value !== "volume") {
                params.set("sort", pill.value);
              }
              const qs = params.toString();
              const href = (qs ? `${basePath}?${qs}` : basePath) as Route;
              return (
                <Link
                  key={pill.value}
                  href={href}
                  className={`rounded-full border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.25em] transition sm:py-1 ${
                    pill.active
                      ? "border-emerald-400/70 bg-emerald-400/20 text-emerald-100"
                      : "border-white/10 bg-white/5 text-white/70 hover:border-emerald-300/60 hover:text-white"
                  }`}
                >
                  {pill.label}
                </Link>
              );
            })}
            {hasActiveFilters ? (
              <Link
                href="/"
                className="rounded-full border border-red-400/60 bg-red-500/10 px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.25em] text-red-100 transition hover:border-red-300 hover:text-white hover:bg-red-500/20 sm:py-1"
              >
                Clear
              </Link>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
