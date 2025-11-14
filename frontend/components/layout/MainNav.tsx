"use client";

import Link from "next/link";

export function MainNav() {
  return (
    <header className="border-b border-white/10 bg-black/30 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
        <Link href="/" className="text-lg font-semibold tracking-tight text-white">
          Reveal Market
        </Link>
        <nav className="flex items-center gap-3 text-sm text-white/80">
          <Link
            href="/docs"
            className="rounded-full border border-white/15 px-4 py-2 text-center transition hover:text-white sm:px-4 sm:py-1"
          >
            Docs
          </Link>
          <Link
            href="/login"
            className="rounded-full bg-brand-500 px-4 py-2 text-center text-sm font-semibold text-white shadow-lg shadow-brand-500/40 transition hover:bg-brand-400 sm:px-4 sm:py-1"
          >
            Log In
          </Link>
        </nav>
      </div>
    </header>
  );
}
