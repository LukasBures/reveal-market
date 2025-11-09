"use client";

import Link from "next/link";

export function MainNav() {
  return (
    <header className="border-b border-white/10 bg-black/50 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
        <Link href="/" className="font-semibold tracking-tight text-lg">
          Reveal Market
        </Link>
        <nav className="flex items-center">
          <Link
            href="/login"
            className="rounded-full bg-brand-500 px-4 py-1 text-sm font-semibold text-white shadow-glow-brand transition hover:bg-brand-400"
          >
            Log In
          </Link>
        </nav>
      </div>
    </header>
  );
}
