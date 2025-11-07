"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const sections = [
  { href: "/docs", label: "Overview" },
  { href: "/docs/getting-started", label: "Getting Started" },
  { href: "/docs/architecture", label: "Architecture" },
  { href: "/docs/api", label: "API Reference" },
];

export function DocsNav() {
  const pathname = usePathname();

  return (
    <aside className="sticky top-4 rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-sm">
      <p className="mb-3 text-xs uppercase tracking-[0.3em] text-slate-500">
        Documentation
      </p>
      <div className="flex flex-col gap-2">
        {sections.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className={clsx(
              "rounded-lg px-3 py-2 transition",
              pathname === section.href
                ? "bg-white/10 text-white"
                : "text-slate-400 hover:bg-white/5 hover:text-white"
            )}
          >
            {section.label}
          </Link>
        ))}
      </div>
    </aside>
  );
}
