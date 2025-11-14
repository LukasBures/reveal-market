"use client";

 "use client";

import { useState } from "react";
import Link from "next/link";

export function MainNav() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-black/30 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
        <Link href="/" className="text-lg font-semibold tracking-tight text-white">
          Reveal Market
        </Link>
        <button
          type="button"
          onClick={() => setMenuOpen((state) => !state)}
          className="rounded-full border border-white/15 px-3 py-1 text-xs uppercase tracking-[0.3em] text-white/80 transition hover:text-white sm:hidden"
          aria-expanded={menuOpen}
          aria-controls="main-nav-menu"
        >
          Menu
        </button>
        <nav
          id="main-nav-menu"
          className={`${
            menuOpen ? "flex" : "hidden"
          } absolute left-0 top-full w-full flex-col gap-2 border-b border-white/10 bg-black/80 px-4 py-4 text-sm text-white/80 sm:static sm:flex sm:w-auto sm:flex-row sm:items-center sm:gap-3 sm:border-none sm:bg-transparent sm:py-0`}
        >
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
