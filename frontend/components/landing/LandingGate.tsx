import Link from "next/link";

import { LandingAccessForm } from "@/components/landing/LandingAccessForm";

const heroStats = [
  { label: "Access", value: "Invite code" },
  { label: "Board status", value: "Private" },
];

const steps = [
  {
    title: "Make your call",
    description: "Pick a market and submit your entry. No public odds board, no copy trading while it's live.",
  },
  {
    title: "Let it play out",
    description: "Our desk watches the event, posts pauses or rule tweaks, and closes the board when action stops.",
  },
  {
    title: "Collect with a receipt",
    description: "When the outcome is final, everyone gets a plain recap of what paid out and why.",
  },
];

const benefits = [
  {
    title: "No copycats",
    description: "Entries stay private until settlement, so sizing up doesn't invite a rush of mirror trades.",
  },
  {
    title: "No sniping",
    description: "With no public order book, there's no incentive to frontrun or chase prints.",
  },
  {
    title: "Receipts, not jargon",
    description: "Settlement notes are written for investors, not engineers.",
  },
  {
    title: "Simple flow",
    description: "Buy a ticket, check back when results land, claim with confidence.",
  },
];

export function LandingGate() {
  return (
    <div className="landing-noise relative flex min-h-screen flex-col overflow-hidden bg-slate-950 text-white">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(124,132,255,0.15),transparent_55%),radial-gradient(circle_at_80%_0%,rgba(123,240,94,0.15),transparent_45%)] opacity-70" />
      <div className="relative z-10 mx-auto flex w-full max-w-7xl flex-1 flex-col gap-12 px-6 py-16">
        <div className="grid gap-8 rounded-[36px] border border-white/10 bg-slate-950/80 p-8 shadow-[0_40px_120px_-60px_rgba(8,47,73,0.8)] lg:grid-cols-[1.1fr_0.9fr]">
          <div className="flex flex-col gap-6 text-center lg:text-left">
            <div className="inline-flex items-center justify-center gap-3 rounded-full border border-white/15 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.55em] text-slate-300 lg:justify-start">
              Private beta
            </div>
            <div className="space-y-4">
              <h1 className="text-4xl font-semibold sm:text-5xl">Hidden while live. Transparent when it counts.</h1>
              <p className="text-base text-slate-300">
                Reveal Market runs invite-only prediction boards. While a market is live, no odds, positions, or sizing
                hit a public feed. When the outcome is final, everyone sees a clean settlement receipt.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-3 lg:justify-start">
              <Link
                href="https://x.com/RevealMarket"
                className="inline-flex items-center justify-center gap-2 rounded-full border border-white/20 px-6 py-2 text-sm font-semibold text-brand-100 transition hover:border-white/40 hover:text-white"
                target="_blank"
                rel="noreferrer"
              >
                <XIcon className="h-4 w-4" aria-hidden />
                Follow @RevealMarket
              </Link>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.45em] text-white/70">
                <span className="h-2 w-2 rounded-full bg-accent-400 shadow-[0_0_12px_rgba(123,240,94,0.7)]" />
                Live gate
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {heroStats.map((stat) => (
                <div key={stat.label} className="rounded-2xl border border-white/10 bg-black/40 p-4">
                  <p className="text-xs uppercase tracking-[0.35em] text-slate-500">{stat.label}</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{stat.value}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="wolf-aura flex flex-col items-center gap-4 overflow-hidden p-6 text-center lg:text-left">
            <div className="relative">
              <div className="absolute inset-0 rounded-full bg-gradient-to-b from-white/25 via-transparent to-transparent blur-3xl opacity-70" />
              <picture>
                <source srcSet="/brand/reveal-wolf-03.webp" type="image/webp" />
                <img
                  src="/brand/reveal-wolf-03.png"
                  alt="Reveal Market wolf illustration"
                  className="relative z-10 w-64 max-w-full drop-shadow-[0_45px_90px_rgba(0,0,0,0.65)]"
                  loading="eager"
                />
              </picture>
            </div>
            <p className="text-sm uppercase tracking-[0.4em] text-white/60">Private board with receipts</p>
            <p className="text-base text-slate-200">The private board that shows its receipts once the story is over.</p>
          </div>
        </div>

        <section className="rounded-[32px] border border-white/10 bg-slate-950/70 p-6 text-slate-200">
          <header className="mb-6 text-center">
            <p className="text-xs uppercase tracking-[0.5em] text-slate-400">How it works</p>
          </header>
          <div className="grid gap-6 text-left md:grid-cols-3">
            {steps.map((step, index) => (
              <div key={step.title} className="halo-card relative overflow-hidden rounded-2xl border border-white/10 p-4">
                <span className="relative z-10 text-xs uppercase tracking-[0.4em] text-slate-400">
                  0{index + 1}. {step.title}
                </span>
                <p className="relative z-10 mt-3 text-sm leading-relaxed text-slate-200">{step.description}</p>
                <div className="pointer-events-none absolute -right-6 top-6 h-12 w-12 rounded-full bg-white/5 blur-2xl" />
              </div>
            ))}
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          {benefits.map((benefit) => (
            <div key={benefit.title} className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
              <p className="text-sm font-semibold text-white">{benefit.title}</p>
              <p className="mt-2 text-sm text-slate-300">{benefit.description}</p>
            </div>
          ))}
        </section>

        <section className="space-y-4 text-center text-slate-200">
          <p className="text-sm uppercase tracking-[0.45em] text-slate-500">Private conviction, public receipts</p>
          <div className="space-y-2 text-sm">
            <p>Make your call while the board stays quiet.</p>
            <p>When the story ends, read the receipt, claim, and move on to the next headline.</p>
            <p>This isn&apos;t another odds board — it&apos;s conviction without the crowding.</p>
          </div>
        </section>
      </div>
      <div className="relative z-10 border-t border-white/5 bg-black/30 px-4 py-12 text-center">
        <div className="mx-auto w-full max-w-md rounded-3xl border border-white/10 bg-slate-950/80 px-6 py-8 shadow-[0_30px_80px_-50px_rgba(15,118,110,0.9)]">
          <p className="text-xs uppercase tracking-[0.5em] text-slate-400">Enter access code</p>
          <p className="mt-2 text-sm text-slate-300">Early access is limited. Use your invite code to continue.</p>
          <div className="mt-6">
            <LandingAccessForm />
          </div>
        </div>
      </div>
    </div>
  );
}

function XIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 120 120"
      role="img"
      aria-label="X logo"
      className={className}
    >
      <path d="M10 10h100v100H10z" fill="currentColor" opacity="0.08" />
      <path
        d="M32 32h18l22 26 24-26h22l-36 38 38 46H100L74 78 46 118H22l38-42z"
        fill="currentColor"
      />
    </svg>
  );
}
