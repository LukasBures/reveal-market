import Link from "next/link";
import Image from "next/image";
import { Fragment } from "react";
import clsx from "clsx";

import { LandingAccessForm } from "@/components/landing/LandingAccessForm";

const heroStats = [
  { label: "Access", value: "Invite code" },
  { label: "Board status", value: "Private" },
];

const steps = [
  {
    title: "Make your call",
    description: "Pick a market and submit your entry. No public board, no copy trading while it's live.",
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

const lifecycle = [
  { label: "Committed", description: "Ticket placed and recorded." },
  { label: "Locked", description: "Board closed; no new entries." },
  { label: "Resolved", description: "Outcome posted with proof." },
  { label: "Settled", description: "Payout path ready." },
  { label: "Claimed", description: "Funds claimed to your wallet." },
] as const;

export function LandingGate() {
  return (
    <div className="landing-noise relative flex min-h-screen flex-col overflow-hidden bg-slate-950 text-white" data-testid="landing-gate">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(124,132,255,0.15),transparent_55%),radial-gradient(circle_at_80%_0%,rgba(123,240,94,0.15),transparent_45%)] opacity-70" />
      <div className="relative z-10 mx-auto flex w-full max-w-7xl flex-1 flex-col gap-12 px-6 py-4">
        <div className="grid gap-8 rounded-[36px] border border-white/10 bg-slate-950/80 p-8 shadow-[0_40px_120px_-60px_rgba(8,47,73,0.8)] lg:grid-cols-[1.1fr_0.9fr]">
          <div className="flex flex-col gap-6 text-center lg:text-left">
            <div className="space-y-4">
              <h1 className="text-4xl font-semibold sm:text-5xl">Hidden while live. Transparent when it counts.</h1>
              <p className="text-base text-slate-300">
                Reveal Market runs invite-only prediction boards. Positions and sizing stay off the public feed until
                settlement. When the outcome is final, everyone sees a clear receipt.
              </p>
              <p className="text-xs uppercase tracking-[0.4em] text-slate-400">Private beta — invite required</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {heroStats.map((stat) => (
                <div key={stat.label} className="rounded-2xl border border-white/10 bg-black/40 p-4">
                  <p className="text-xs uppercase tracking-[0.35em] text-slate-500">{stat.label}</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{stat.value}</p>
                </div>
              ))}
            </div>
            <div className="relative overflow-hidden rounded-3xl border border-accent-400/50 bg-slate-950/80 p-5 text-center shadow-[0_25px_90px_-45px_rgba(123,240,94,0.65)]">
              <div className="pointer-events-none absolute -inset-[1px] rounded-[22px] bg-gradient-to-r from-accent-400/25 via-emerald-400/15 to-cyan-400/20 blur-2xl" />
              <p className="text-xs uppercase tracking-[0.5em] text-slate-200">Enter access code</p>
              <p className="mt-2 text-sm text-slate-300">Use your invite code to continue.</p>
              <div className="relative mt-6 flex w-full flex-col items-center gap-4 text-center">
                <LandingAccessForm />
              </div>
            </div>
          </div>
          <div className="wolf-aura flex h-full flex-col items-center justify-center gap-4 rounded-[32px] border border-white/10 bg-slate-950/70 p-6 text-center shadow-[0_25px_70px_-40px_rgba(0,0,0,0.6)]">
            <Image
              src="/brand/reveal-wolf-03.webp"
              alt="Reveal Market wolf illustration"
              width={256}
              height={256}
              className="mx-auto h-auto w-64 max-w-full rounded-[28px] object-contain drop-shadow-[0_45px_90px_rgba(0,0,0,0.65)]"
              priority
            />
          </div>
        </div>

        <section className="rounded-[32px] border border-white/10 bg-slate-950/70 p-6 text-slate-200">
          <header className="mb-6 text-center">
            <p className="text-xs uppercase tracking-[0.5em] text-slate-400">Flow to payout</p>
            <p className="mt-2 text-sm text-slate-300">The same lifecycle you&apos;ll see on your dashboard.</p>
          </header>
          <div className="mt-3 rounded-xl border border-emerald-400/60 bg-gradient-to-r from-slate-900/60 via-black/60 to-slate-900/40 p-3 shadow-[0_0_28px_rgba(123,240,94,0.35)] relative overflow-hidden transition-shadow">
            <div className="pointer-events-none absolute inset-0 bg-[length:240%_160%] bg-[linear-gradient(120deg,rgba(123,240,94,0)_0%,rgba(123,240,94,0.22)_40%,rgba(123,240,94,0)_75%)] opacity-35 blur-[1px] mix-blend-screen animate-[statusFlow_5.5s_linear_infinite]" />
            <div className="flex items-center justify-between text-[11px] uppercase tracking-[0.25em] text-slate-400">
              <span>Lifecycle</span>
              <span className="text-[10px] text-emerald-200">Clear path to payout</span>
            </div>
            <div className="relative mt-3 overflow-hidden rounded-lg border border-white/5 bg-black/40 p-3 shadow-inner shadow-black/30">
              <div className="pointer-events-none absolute inset-0 bg-[length:220%_140%] bg-[linear-gradient(120deg,rgba(123,240,94,0)_0%,rgba(123,240,94,0.18)_35%,rgba(123,240,94,0)_70%)] opacity-70 mix-blend-screen animate-[statusFlow_4.2s_linear_infinite]" />
              <div className="relative flex flex-col items-stretch gap-2 overflow-x-hidden overflow-y-visible md:flex-row md:items-stretch md:justify-between md:gap-3 md:overflow-x-auto md:pb-1">
                {lifecycle.map((stage, idx) => {
                  const isCurrent = idx === lifecycle.length - 2; // settled as focus
                  const isComplete = idx < lifecycle.length - 1;
                  const bubbleClass = isCurrent
                    ? "border-emerald-300/80 bg-emerald-500/20 text-emerald-50 shadow-[0_0_0_2px_rgba(123,240,94,0.35)]"
                    : isComplete
                      ? "border-emerald-400/50 bg-emerald-500/10 text-emerald-100"
                      : "border-white/10 bg-white/5 text-slate-200";
                  const connectorClass = isComplete
                    ? "from-emerald-400/80 via-emerald-300/40 to-emerald-400/70"
                    : "from-white/15 via-white/10 to-white/15";
                  const arrowClass = isComplete ? "text-emerald-200" : "text-slate-500";
                  return (
                    <Fragment key={stage.label}>
                <div
                  className={clsx(
                    "flex min-w-0 flex-col gap-0.5 self-stretch rounded-lg border px-3 py-2 text-left transition-colors md:min-w-[140px] md:flex-1 h-full",
                    bubbleClass,
                  )}
                >
                        <span className="text-[11px] uppercase tracking-[0.2em]">{stage.label}</span>
                        <span className="text-[11px] text-slate-300 leading-snug min-h-[34px]">{stage.description}</span>
                      </div>
                      {idx < lifecycle.length - 1 ? (
                        <div className="hidden items-center gap-2 md:flex md:flex-1 md:justify-center">
                          <div className={clsx("h-[2px] w-10 rounded-full bg-gradient-to-r md:w-full", connectorClass)} />
                          <svg className={clsx("h-4 w-4", arrowClass)} viewBox="0 0 24 24" fill="none" aria-hidden>
                            <path
                              d="M6 5l8 7-8 7"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </div>
                      ) : null}
                    </Fragment>
                  );
                })}
              </div>
            </div>
            <p className="mt-2 text-[11px] text-slate-400">All phases clear to claim.</p>
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
          <p className="text-sm uppercase tracking-[0.45em] text-slate-500">Private while live, provable at the end.</p>
        </section>
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
