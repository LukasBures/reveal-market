"use client";

import { Suspense, useEffect, useRef, useState } from "react";
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
    loading: () => {
      let label = "Connect Wallet";
      try {
        const addr = localStorage.getItem("rm_last_wallet_address");
        if (addr) label = `${addr.slice(0, 6)}...${addr.slice(-4)}`;
      } catch { /* SSR / private browsing */ }
      return (
        <div>
          <span className="inline-flex items-center justify-center rounded-full bg-brand-500 px-3 py-2 text-xs font-semibold text-white select-none shadow-lg shadow-brand-500/40 md:min-w-[9.5rem] md:px-5 md:py-2.5 md:text-sm">
            {label}
          </span>
        </div>
      );
    },
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
 * Renders two completely separate headers — one for mobile, one for desktop —
 * so each can be styled independently without responsive-prefix fights.
 */
export function MainNav() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const firstLinkRef = useRef<HTMLAnchorElement | null>(null);
  const pathname = usePathname();
  const isLandingPage = pathname === "/";
  const isCategoryPage = /^\/[a-z][a-z0-9-]*$/.test(pathname) && parseCategorySlug(pathname.slice(1)) !== null;
  const showFiltersBar = isLandingPage || isCategoryPage;

  // Keyboard handling: Escape closes menu, Tab traps focus inside panel
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
          document.querySelectorAll<HTMLElement>(
            "#main-mobile-nav a, #main-mobile-nav button, #main-mobile-nav input",
          ),
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
    const searchInput = document.querySelector<HTMLElement>("#main-mobile-nav input");
    if (searchInput) searchInput.focus();
    return () => window.removeEventListener("keydown", handler);
  }, [isMobileMenuOpen]);

  // Prevent page scroll while mobile menu is open
  useEffect(() => {
    document.body.style.overflow = isMobileMenuOpen ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [isMobileMenuOpen]);

  // Shared logo element (used in both headers)
  const logoImg = (
    <div className="relative aspect-[25/7] w-[130px] md:w-[160px]">
      <Image
        src="/brand/reveal-logo-wordmark.svg"
        alt="Reveal Market"
        fill
        sizes="(max-width: 767px) 130px, 160px"
        priority
        unoptimized
        className="select-none object-contain"
      />
    </div>
  );
  const logoLink = externalHomeHref ? (
    <a
      href={externalHomeHref}
      className="flex flex-shrink-0 cursor-pointer select-none items-center text-white transition hover:opacity-90"
      onClick={() => setIsMobileMenuOpen(false)}
    >
      {logoImg}
    </a>
  ) : (
    <Link
      href={internalHomeHref}
      className="flex flex-shrink-0 cursor-pointer select-none items-center text-white transition hover:opacity-90"
      onClick={() => setIsMobileMenuOpen(false)}
    >
      {logoImg}
    </Link>
  );

  // Animated hamburger button (mobile only)
  const hamburgerButton = (
    <button
      type="button"
      className="relative flex h-10 w-10 items-center justify-center rounded-full border border-white/20 transition hover:border-white"
      aria-expanded={isMobileMenuOpen}
      aria-controls="main-mobile-nav"
      aria-label={isMobileMenuOpen ? "Close navigation" : "Open navigation"}
      onClick={() => setIsMobileMenuOpen((prev) => !prev)}
      ref={triggerRef}
    >
      <div className="flex h-4 w-5 flex-col items-center justify-between">
        <span className={`block h-[2px] w-5 rounded-full bg-white transition-all duration-300 ${isMobileMenuOpen ? "translate-y-[7px] rotate-45" : ""}`} />
        <span className={`block h-[2px] w-5 rounded-full bg-white transition-all duration-300 ${isMobileMenuOpen ? "opacity-0" : ""}`} />
        <span className={`block h-[2px] w-5 rounded-full bg-white transition-all duration-300 ${isMobileMenuOpen ? "-translate-y-[7px] -rotate-45" : ""}`} />
      </div>
    </button>
  );

  return (
    <>
      {/* ══════════════════════════════════════════════════════════════════
          MOBILE HEADER  (visible below md breakpoint — < 768px)
          Layout:
            Row 1  [60px]  Logo ←——————— Connect Wallet  ☰
            Row 2  [44px]  ← Category chips →   (home/category pages only)
      ══════════════════════════════════════════════════════════════════ */}
      <header
        className={`fixed left-0 right-0 top-0 z-50 border-b border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] md:hidden ${showFiltersBar ? "h-[104px]" : "h-[60px]"}`}
      >
        {/* Decorative top accent line */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
        {/* Radial glow behind nav row */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-[60px] bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
        {showFiltersBar ? (
          <div className="pointer-events-none absolute inset-x-0 top-[60px] h-[44px] bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
        ) : null}

        {/* Row 1: Logo (left) + Connect Wallet + Hamburger (right) */}
        <div className="mx-auto flex h-[60px] max-w-7xl items-center justify-between px-4" data-testid="main-nav">
          {logoLink}
          <div className="flex items-center gap-2">
            {/* Compact ConnectWallet — override min-width and padding for the tight row */}
            <div className="[&>div>button]:min-w-0 [&>div>button]:px-3 [&>div>button]:py-2 [&>div>button]:text-xs [&>div>span]:min-w-0 [&>div>span]:px-3 [&>div>span]:py-2 [&>div>span]:text-xs drop-shadow-[0_0_25px_rgba(123,240,94,0.45)]">
              <ConnectWalletButton />
            </div>
            {hamburgerButton}
          </div>
        </div>

        {/* Row 2: Category chips (home / category pages only) */}
        {showFiltersBar ? (
          <Suspense fallback={null}>
            <HomeFiltersBar mobile />
          </Suspense>
        ) : null}

        {/* Backdrop — always in DOM so opacity transition works */}
        <div
          className={`fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-300 ${
            isMobileMenuOpen ? "opacity-100" : "pointer-events-none opacity-0"
          }`}
          onClick={() => setIsMobileMenuOpen(false)}
          aria-hidden="true"
        />

        {/* Slide-down menu panel */}
        <div
          id="main-mobile-nav"
          className={`absolute inset-x-0 top-[60px] z-50 border-b border-white/10 bg-slate-950/95 backdrop-blur-2xl transition-all duration-300 ${
            isMobileMenuOpen
              ? "translate-y-0 opacity-100"
              : "pointer-events-none -translate-y-4 opacity-0"
          }`}
        >
          <nav className="mx-auto max-w-7xl px-4 py-5">
            <div className="mb-5">
              <HeroSearch
                showButton={false}
                showIcon
                placeholder="Search markets..."
                containerClassName="px-3 py-2.5"
                inputClassName="text-sm placeholder:text-white/40"
              />
            </div>
            <div className="mb-4 h-px bg-white/10" />
            <div className="flex flex-col gap-2">
              <Link
                href={"/dashboard" as Route}
                className={`rounded-xl px-4 py-3 text-base font-semibold text-white/80 transition hover:bg-white/10 hover:text-white ${pathname === "/dashboard" ? "bg-white/10 text-white" : ""}`}
                onClick={() => setIsMobileMenuOpen(false)}
                ref={firstLinkRef}
              >
                Dashboard
              </Link>
              <Link
                href={"/proofs" as Route}
                className={`rounded-xl px-4 py-3 text-base font-semibold text-white/80 transition hover:bg-white/10 hover:text-white ${pathname === "/proofs" ? "bg-white/10 text-white" : ""}`}
                onClick={() => setIsMobileMenuOpen(false)}
              >
                Proofs
              </Link>
            </div>
          </nav>
        </div>
      </header>

      {/* ══════════════════════════════════════════════════════════════════
          DESKTOP HEADER  (visible at md breakpoint and above — ≥ 768px)
          Layout:
            Row 1  [72px]  Logo ←— Search · Proofs · Dashboard —→ Connect Wallet
            Row 2  [48px]  ← Category chips ————————— Sort pills →  (home/category pages only)
      ══════════════════════════════════════════════════════════════════ */}
      <header
        className={`fixed left-0 right-0 top-0 z-50 hidden border-b border-white/10 bg-black/50 backdrop-blur-2xl px-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] md:block ${showFiltersBar ? "h-[120px]" : "h-[72px]"}`}
      >
        {/* Decorative top accent line */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-500/40 to-transparent" />
        {/* Radial glow behind nav row */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-[72px] bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
        {showFiltersBar ? (
          <div className="pointer-events-none absolute inset-x-0 top-[72px] h-[48px] bg-[radial-gradient(circle_at_top,_rgba(124,132,255,0.18),_transparent_70%)]" />
        ) : null}

        {/* Single nav row: Logo | Search + links (centered) | ConnectWallet */}
        <div className="relative mx-auto flex h-[72px] max-w-7xl items-center gap-4 px-4">
          {logoLink}

          <nav className="flex flex-1 items-center justify-center gap-6 text-base font-semibold tracking-wide text-white/80">
            <div className="w-72 lg:w-80">
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
                pathname === "/proofs" ? "bg-white/10 text-white" : "hover:bg-white/10 hover:text-white"
              }`}
            >
              Proofs
            </Link>
            <Link
              href="/dashboard"
              className={`rounded-full px-3 py-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 ${
                pathname === "/dashboard" ? "bg-white/10 text-white" : "hover:bg-white/10 hover:text-white"
              }`}
            >
              Dashboard
            </Link>
          </nav>

          <div className="flex min-w-[200px] items-center justify-end">
            <div className="drop-shadow-[0_0_25px_rgba(123,240,94,0.45)]">
              <ConnectWalletButton />
            </div>
          </div>
        </div>

        {/* Filter bar row (home / category pages only) */}
        {showFiltersBar ? (
          <Suspense fallback={null}>
            <HomeFiltersBar />
          </Suspense>
        ) : null}
      </header>

      {/* Content offset spacer — matches whichever header is active */}
      <div
        className={showFiltersBar ? "h-[104px] bg-[#010314] md:h-[120px]" : "h-[60px] bg-[#010314] md:h-[72px]"}
        aria-hidden="true"
      />
    </>
  );
}

function HomeFiltersBar({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const rawSortParam = searchParams.get("sort");
  const sortBy = (() => {
    if (rawSortParam === "newest") return "recent";
    if (rawSortParam === "trending") return "popularity";
    return "totalVolume";
  })();

  const pathSegment = pathname === "/" ? null : pathname.slice(1);
  const activeCategory = pathSegment ? parseCategorySlug(pathSegment) : null;
  const isHome = pathname === "/";
  const hasActiveFilters = Boolean(activeCategory) || rawSortParam !== null;
  const basePath = activeCategory ? `/${activeCategory.slug}` : "/";

  const sortPills = [
    { label: "Trending", value: "trending", active: sortBy === "popularity" },
    { label: "Volume", value: "volume", active: sortBy === "totalVolume" },
    { label: "Newest", value: "newest", active: sortBy === "recent" },
  ];

  const categoryChips = HERO_CATEGORY_FILTERS.map((category) => {
    const isAll = category.toLowerCase() === "all";
    const slug = categorySlugFromLabel(category) ?? category.toLowerCase().replace(/[^a-z0-9-]/g, "-");
    const isActive = isAll ? isHome : activeCategory?.slug === slug;
    const href = (isAll ? "/" : `/${slug}`) as Route;
    return { category, slug, isActive, href };
  });

  if (mobile) {
    return (
      <div className="border-t border-white/5 bg-black/80 text-xs text-white/80 backdrop-blur">
        {/* Categories only — full width horizontally scrollable, no sort pills */}
        <div className="mx-auto flex h-[44px] max-w-7xl items-center px-4">
          <div className="relative w-full">
            <div className="pointer-events-none absolute left-0 top-0 h-full w-8 bg-gradient-to-r from-black/80 to-transparent opacity-90" />
            <div className="pointer-events-none absolute right-0 top-0 h-full w-8 bg-gradient-to-l from-black/80 to-transparent opacity-90" />
            <div className="no-scrollbar flex snap-x snap-mandatory gap-2 overflow-x-auto">
              {categoryChips.map(({ category, isActive, href }) => (
                <Link
                  key={category}
                  href={href}
                  className={`relative snap-start rounded-full border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.25em] transition ${
                    isActive
                      ? "border-brand-400/80 bg-brand-400/20 text-white shadow-[0_0_12px_rgba(123,240,94,0.3)]"
                      : "border-white/10 bg-white/5 text-white/80 hover:border-brand-400/60 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  <span className="relative">{category}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Desktop: single 48px row with categories + sort side by side
  return (
    <div className="border-t border-white/5 bg-black/80 text-xs text-white/80 backdrop-blur">
      <div className="mx-auto flex h-[48px] w-full max-w-7xl items-center px-4">
        <div className="flex w-full items-center gap-2">
          {/* Category chips — horizontally scrollable */}
          <div className="relative min-w-0 flex-1">
            <div className="pointer-events-none absolute left-0 top-0 h-full w-10 bg-gradient-to-r from-black/80 to-transparent opacity-90" />
            <div className="pointer-events-none absolute right-0 top-0 h-full w-10 bg-gradient-to-l from-black/80 to-transparent opacity-90" />
            <div className="no-scrollbar flex snap-x snap-mandatory gap-2 overflow-x-auto pr-6">
              {categoryChips.map(({ category, isActive, href }) => (
                <Link
                  key={category}
                  href={href}
                  className={`relative snap-start rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.25em] transition ${
                    isActive
                      ? "border-brand-400/80 bg-brand-400/20 text-white"
                      : "border-white/10 bg-white/5 text-white/80 hover:border-brand-400/60 hover:bg-white/10 hover:text-white"
                  }`}
                >
                  <span className="relative">{category}</span>
                </Link>
              ))}
            </div>
          </div>
          {/* Sort pills */}
          <div className="flex flex-none items-center gap-2">
            {sortPills.map((pill) => {
              const params = new URLSearchParams();
              if (pill.value !== "volume") params.set("sort", pill.value);
              const qs = params.toString();
              const href = (qs ? `${basePath}?${qs}` : basePath) as Route;
              return (
                <Link
                  key={pill.value}
                  href={href}
                  className={`rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.25em] transition ${
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
                className="rounded-full border border-red-400/60 bg-red-500/10 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.25em] text-red-100 transition hover:border-red-300 hover:bg-red-500/20 hover:text-white"
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
