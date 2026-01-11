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
    title: "Start Here",
    pages: [
      { href: "/docs", label: "Overview" },
      { href: "/docs/getting-started", label: "Getting Started" },
      { href: "/docs/faq", label: "FAQ" },
    ],
  },
  {
    title: "Trust & Access",
    pages: [
      { href: "/docs/privacy-security", label: "Privacy & Security" },
      { href: "/legal", label: "Legal" },
    ],
  },
];

export function DocsNav() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-4 self-start rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-sm">
      <p className="mb-3 text-xs uppercase tracking-[0.35em] text-slate-400">Documentation</p>
      <div className="flex flex-col gap-4">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">{section.title}</p>
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
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Need help?</p>
          <p className="mt-2 text-slate-200">Tell us what you need and we&apos;ll route your note to the right person.</p>
          <Link
            href="/contact"
            className="mt-4 inline-flex items-center justify-center rounded-full bg-brand-500 px-5 py-3 text-sm font-semibold uppercase tracking-[0.25em] text-white transition hover:bg-brand-400"
          >
            Contact us
          </Link>
        </div>
      </div>
    </aside>
  );
}
