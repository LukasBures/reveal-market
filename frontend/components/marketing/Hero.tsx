"use client";

import Link from "next/link";
import Image from "next/image";
import { categorySlugFromLabel } from "@/lib/slugs";
import { HeroSearch } from "./HeroSearch";

type HeroStat = {
  label: string;
  value: string;
};

const heroHighlights = [
  {
    title: "Hidden while live",
    description: "Entries stay sealed until the market settles, so sizing never hits a public board.",
  },
  {
    title: "Receipts on settle",
    description: "When outcomes post, everyone sees a clear, human-readable breakdown.",
  },
  {
    title: "Ops that talks",
    description: "Pauses, rule tweaks, and claims get called out before you make a move.",
  },
] as const;

type HeroProps = {
  stats: HeroStat[];
};

const heroCategories = ["Crypto", "Finance", "Sports", "Politics", "Geopolitics", "Tech", "Elections"];

export function Hero({ stats }: HeroProps) {
  return (
    <section className="space-y-8 px-4 pb-10 pt-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <div className="space-y-3 rounded-[32px] border border-white/10 bg-black/30 p-6 shadow-[0_30px_90px_-50px_rgba(14,21,56,0.8)] lg:grid lg:grid-cols-2 lg:gap-8 lg:p-8">
          <div className="space-y-3">
            <h1 className="font-display text-4xl leading-tight text-white md:text-5xl lg:text-6xl">
              Trade the story without broadcasting your moves.
            </h1>
            <p className="text-base text-slate-200 md:text-lg">
              Reveal Market is an invite-only arena for conviction on sports, politics, and macro moments. Positions stay
              private while markets play out; when they settle, you get a clean receipt of who got paid and why.
            </p>
          </div>
          <div className="grid w-full gap-3 sm:grid-cols-2">
            {stats.map((stat) => (
              <div
                key={stat.label}
                className="relative overflow-hidden rounded-2xl border border-white/10 bg-white/5 p-4 shadow-[0_20px_40px_rgba(0,0,0,0.3)]"
              >
                <div className="pointer-events-none absolute inset-x-4 top-2 h-12 rounded-full bg-gradient-to-r from-accent-400/25 via-white/10 to-brand-500/25 blur-2xl" />
                <p className="text-xs uppercase tracking-[0.3em] text-white/70">
                  {stat.label === "Total markets tracked" ? "Total markets" : stat.label}
                </p>
                <p className="mt-2 text-2xl font-semibold text-white">{stat.value}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="space-y-3 rounded-[24px] border border-white/10 bg-slate-950/50 p-5 shadow-[0_20px_60px_-50px_rgba(14,21,56,0.7)]">
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
      </div>
    </section>
  );
}
