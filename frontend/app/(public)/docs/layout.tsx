import type { Metadata } from "next";
import type { ReactNode } from "react";
import dynamic from "next/dynamic";

const DocsNavPanel = dynamic(
  () =>
    import("@/components/docs/DocsNav").then((mod) => ({
      default: mod.DocsNav,
    })),
  {
    loading: () => (
      <aside className="sticky top-4 self-start rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-sm">
        <p className="mb-3 text-xs uppercase tracking-[0.35em] text-slate-400">Documentation</p>
        <div className="space-y-3">
          {[...Array(4)].map((_, index) => (
            <div key={index} className="space-y-2">
              <div className="h-3 w-20 animate-pulse rounded-full bg-white/10" />
              <div className="h-9 w-full animate-pulse rounded-xl bg-white/5" />
              <div className="h-9 w-full animate-pulse rounded-xl bg-white/5" />
            </div>
          ))}
        </div>
      </aside>
    ),
  },
);

export const metadata: Metadata = {
  title: {
    default: "Reveal Market Docs",
    template: "%s | Reveal Market Docs",
  },
};

export const revalidate = 300;

export default function DocsLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="mx-auto grid max-w-7xl gap-8 px-4 py-12 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] lg:grid-cols-[minmax(240px,0.4fr)_minmax(320px,0.6fr)]">
      <DocsNavPanel />
      <article className="flex-1 space-y-6 rounded-2xl border border-white/10 bg-slate-950/60 p-6 text-slate-200">
        <div>{children}</div>
      </article>
    </div>
  );
}
