import Link from "next/link";

import { LandingAccessForm } from "@/components/landing/LandingAccessForm";

const heroStats = [
  { label: "Commit phase", value: "Sealed" },
  { label: "Settlement", value: "Groth16" },
];

const steps = [
  {
    title: "Sealed Commitments",
    description:
      "Participants buy tickets via hashed commits. No one — including the operator — can inspect odds, flows, or position sizes.",
  },
  {
    title: "Lock & Resolve",
    description:
      "Once the oracle finalizes an event, the settlement module validates the commit set, rejects late entries, and computes payouts.",
  },
  {
    title: "Proof-Backed Settlement",
    description:
      "A Groth16 proof confirms totals, rake, and per-ticket rewards before any winnings are released. Losing tickets stay private forever.",
  },
];

const benefits = [
  {
    title: "No Herding or Copy-Trading",
    description: "Hidden orderflow removes cascades, mirror trades, and odds-chasing pressure.",
  },
  {
    title: "No MEV or Sniping",
    description: "Sealed commits + private relays close off frontrunning and mempool analysis.",
  },
  {
    title: "Verifiable Fairness",
    description: "zk-proofs validate every pool. No trusted operator, no secret math.",
  },
  {
    title: "Simple Consumer UX",
    description: "Buy a ticket, come back for a proof-backed claim — no public odds board required.",
  },
];



export function LandingGate() {
  return (
    <div className="landing-noise relative flex min-h-screen flex-col overflow-hidden bg-slate-950 text-white">
      <div className="relative z-10 mx-auto flex w-full max-w-6xl flex-1 flex-col gap-12 px-6 py-16">
        <div className="grid gap-8 rounded-3xl border border-white/10 bg-slate-950/80 p-8 shadow-[0_40px_120px_-60px_rgba(8,47,73,0.8)] lg:grid-cols-2">
          <div className="flex flex-col gap-6 text-center lg:text-left">
            <p className="text-xs uppercase tracking-[0.55em] text-slate-400">Private beta</p>
            <p className="text-sm uppercase tracking-[0.6em] text-slate-300">Reveal Market</p>
            <div className="space-y-4">
              <h1 className="text-4xl font-semibold sm:text-5xl">Private while live. Provable at the end.</h1>
              <p className="text-base text-slate-300">
                Reveal Market runs sealed prediction markets on Horizen. While a market is live, no odds, positions, or
                orderflow are visible — eliminating herding, copy-trading, and MEV sniping. After resolution, a succinct
                zk-proof verifies that the pool math and payouts are correct, making settlement indisputable.
              </p>
            </div>
            <div>
              <Link
                href="https://x.com/RevealMarket"
                className="inline-flex items-center justify-center gap-2 rounded-full border border-white/20 px-6 py-2 text-sm font-semibold text-brand-100 transition hover:border-white/40 hover:text-white"
                target="_blank"
                rel="noreferrer"
              >
                <XIcon className="h-4 w-4" aria-hidden />
                Follow @RevealMarket
              </Link>
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-gradient-to-b from-slate-900/80 to-slate-950/60 p-6 text-center lg:text-left">
            <p className="text-sm uppercase tracking-[0.4em] text-slate-400">Proof-ready settlement stack</p>
            <p className="mt-3 text-lg text-slate-100">
              Sealed commit phases, private relayers, and Groth16-backed settlement give partners verifiable fairness without exposing live orderflow.
            </p>
            <div className="mt-6 grid gap-4 text-left sm:grid-cols-3">
              {heroStats.map((stat) => (
                <div key={stat.label} className="rounded-2xl border border-white/10 bg-black/40 p-4">
                  <p className="text-xs uppercase tracking-[0.35em] text-slate-500">{stat.label}</p>
                  <p className="mt-1 text-2xl font-semibold text-white">{stat.value}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <section className="rounded-3xl border border-white/5 bg-gradient-to-b from-slate-900/70 to-slate-950/40 p-6 text-slate-200">
          <header className="mb-4 text-center">
            <p className="text-xs uppercase tracking-[0.5em] text-slate-400">How it works</p>
          </header>
          <div className="grid gap-6 text-left md:grid-cols-3">
            {steps.map((step) => (
              <div key={step.title} className="rounded-2xl border border-white/10 bg-black/40 p-4">
                <p className="text-xs uppercase tracking-[0.4em] text-slate-500">{step.title}</p>
                <p className="mt-3 text-sm leading-relaxed text-slate-200">{step.description}</p>
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
          <p className="text-sm uppercase tracking-[0.45em] text-slate-500">Provable, fair, private</p>
          <div className="space-y-2 text-sm">
            <p>Commit → lock → proof-backed settle.</p>
            <p>Blind pari-mutuel + fixed-odds engines pair with consumer UX, verifiable cryptography, and scalable creator distribution.</p>
            <p>This isn&apos;t another odds board — it&apos;s a new prediction primitive.</p>
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
