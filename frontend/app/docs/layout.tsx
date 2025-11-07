import type { Metadata } from "next";
import Link from "next/link";
import clsx from "clsx";
import { DocsNav } from "@/components/docs/DocsNav";

export const metadata: Metadata = {
  title: {
    default: "Reveal Market Docs",
    template: "%s | Reveal Market Docs",
  },
};

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname =
    typeof window !== "undefined"
      ? window.location.pathname
      : undefined;
  const crumbs = pathname
    ? pathname
        .split("/")
        .filter(Boolean)
        .map((segment, idx, arr) => {
          const href = `/${arr.slice(0, idx + 1).join("/")}`;
          return { label: segment.replace(/-/g, " "), href };
        })
    : [];

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-12 lg:flex-row">
      <DocsNav />
      <article className="flex-1 space-y-6 rounded-2xl border border-white/10 bg-slate-950/60 p-6 text-slate-200">
        {crumbs.length > 0 && (
          <nav className="text-xs uppercase tracking-[0.3em] text-slate-500">
            <ol className="flex flex-wrap items-center gap-2">
              <li>
                <Link href="/docs" className="hover:text-white">
                  Docs
                </Link>
              </li>
              {crumbs.map((crumb, idx) => (
                <li key={crumb.href} className="flex items-center gap-2">
                  <span>/</span>
                  <Link
                    href={crumb.href}
                    className={clsx(
                      "hover:text-white capitalize",
                      idx === crumbs.length - 1 && "text-white"
                    )}
                  >
                    {crumb.label}
                  </Link>
                </li>
              ))}
            </ol>
          </nav>
        )}
        <div>{children}</div>
      </article>
    </div>
  );
}
