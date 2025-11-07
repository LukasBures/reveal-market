"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

type NavSection = {
  title: string;
  pages: { href: string; label: string }[];
};

const sections: NavSection[] = [
  {
    title: "Foundation",
    pages: [
      { href: "/docs", label: "Overview" },
      { href: "/docs/manifesto", label: "Manifesto" },
      { href: "/docs/the-story", label: "The Story So Far" },
    ],
  },
  {
    title: "Platform",
    pages: [
      { href: "/docs/getting-started", label: "Getting Started" },
      { href: "/docs/architecture", label: "Architecture" },
      { href: "/docs/core-infrastructure", label: "Core Infrastructure" },
      { href: "/docs/privacy-security", label: "Privacy & Security" },
      { href: "/docs/integrations", label: "Integrations" },
    ],
  },
  {
    title: "Economy",
    pages: [
      { href: "/docs/marketplace", label: "Marketplace" },
      { href: "/docs/tokenomics", label: "Tokenomics" },
      { href: "/docs/tiers-fees", label: "Tiers & Fees" },
      { href: "/docs/referrals", label: "Referrals" },
      { href: "/docs/faq", label: "FAQ" },
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
      </div>
    </aside>
  );
}
