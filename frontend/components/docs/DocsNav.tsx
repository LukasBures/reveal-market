"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

type NavSection = {
  title: string;
  pages: { href: Route; label: string }[];
};

const sections: NavSection[] = [
  {
    title: "Vision",
    pages: [
      { href: "/docs", label: "Investor Overview" },
      { href: "/docs/manifesto", label: "Manifesto" },
      { href: "/docs/the-story", label: "Traction & Story" },
    ],
  },
  {
    title: "Roadmap",
    pages: [
      { href: "/docs/roadmap", label: "Execution Roadmap" },
      { href: "/docs/marketplace", label: "Marketplace Flywheel" },
    ],
  },
  {
    title: "Tokenomics",
    pages: [
      { href: "/docs/tokenomics", label: "Tokenomics" },
      { href: "/docs/tiers-fees", label: "Tiers & Fees" },
      { href: "/docs/referrals", label: "Referral Engine" },
    ],
  },
  {
    title: "Infrastructure",
    pages: [
      { href: "/docs/architecture", label: "Architecture" },
      { href: "/docs/core-infrastructure", label: "Core Infrastructure" },
      { href: "/docs/privacy-security", label: "Privacy & Security" },
      { href: "/docs/integrations", label: "Integrations" },
      { href: "/docs/getting-started", label: "Partner Onboarding" },
    ],
  },
  {
    title: "Legal & FAQ",
    pages: [
      { href: "/docs/faq", label: "FAQ" },
      { href: "/legal", label: "Legal Center" },
    ],
  },
];

export function DocsNav() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-sm">
      <p className="mb-3 text-xs uppercase tracking-[0.3em] text-slate-500">
        Documentation
      </p>
      <div className="flex flex-col gap-4">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
              {section.title}
            </p>
            <div className="flex flex-col gap-1">
              {section.pages.map((page) => {
                const active = pathname === page.href;
                return (
                  <Link
                    key={page.href}
                    href={page.href}
                    className={clsx(
                      "rounded-lg px-3 py-2 transition text-sm",
                      active
                        ? "bg-white/15 text-white shadow-inner"
                        : "text-slate-400 hover:bg-white/5 hover:text-white"
                    )}
                  >
                    {page.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
        <div className="rounded-xl border border-white/10 bg-white/5 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
            Need answers fast?
          </p>
          <p className="mt-2 text-slate-200">
            Book a diligence call and walk through the stack with the founding team.
          </p>
          <a
            href="mailto:hello@revealmarket.xyz?subject=Reveal%20Market%20Docs%20Inquiry"
            className="mt-4 inline-flex items-center justify-center rounded-full bg-white px-4 py-2 text-sm font-semibold text-black"
          >
            Connect With The Team
          </a>
        </div>
      </div>
    </aside>
  );
}
