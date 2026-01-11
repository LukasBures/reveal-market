"use client";

import Link from "next/link";
import { categorySlugFromLabel } from "@/lib/slugs";
import { HeroSearch } from "./HeroSearch";

type HeroStat = {
  label: string;
  value: string;
};

type HeroProps = {
  stats: HeroStat[];
};

const heroCategories = ["Crypto", "Finance", "Sports", "Politics", "Geopolitics", "Tech", "Elections"];

export function Hero({ stats }: HeroProps) {
  return (
    <section className="space-y-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 rounded-[32px] border border-white/10 bg-black/30 p-6 shadow-[0_30px_90px_-50px_rgba(14,21,56,0.8)] lg:p-8">
        <h1 className="font-display text-3xl leading-tight text-white sm:text-4xl md:text-5xl lg:text-6xl">
          Trade the story without broadcasting your moves.
        </h1>
        <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
          <div className="space-y-4">
            <p className="text-base text-slate-200 md:text-lg">
              Reveal Market keeps tickets private while the board is live. You size your conviction on sports, politics, or
              macro events without tipping the room. When a market settles, you get a clean receipt of what paid and why.
            </p>
          </div>
          <div className="grid w-full gap-3 sm:grid-cols-2">
            {stats.map((stat) => (
              <div
                key={stat.label}
                className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-4 shadow-[0_20px_40px_rgba(0,0,0,0.3)]"
              >
                <div className="pointer-events-none absolute inset-x-4 top-2 h-12 rounded-full bg-gradient-to-r from-accent-400/25 via-white/10 to-brand-500/25 blur-2xl" />
                <p className="text-xs uppercase tracking-[0.2em] text-white/70 sm:tracking-[0.3em] break-words">
                  {stat.label === "Total markets tracked" ? "Total markets" : stat.label}
                </p>
                <p className="mt-2 text-2xl font-semibold text-white">{stat.value}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mx-auto flex max-w-7xl flex-col gap-3 rounded-[24px] border border-white/10 bg-slate-950/50 p-5 shadow-[0_20px_60px_-50px_rgba(14,21,56,0.7)]">
        <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
          {heroCategories.map((category) => {
            const slug = categorySlugFromLabel(category) ?? category.toLowerCase().replace(/[^a-z0-9-]/g, "-");
            return (
              <Link
                key={category}
                href={`/categories/${encodeURIComponent(slug)}`}
                className="group rounded-full border border-white/10 bg-slate-900/30 px-4 py-2 text-sm text-slate-100 transition hover:border-brand-400/60 hover:text-white"
              >
                <span className="text-xs uppercase tracking-[0.4em] text-slate-400">{category}</span>
              </Link>
            );
          })}
        </div>
        <HeroSearch />
      </div>
    </section>
  );
}
