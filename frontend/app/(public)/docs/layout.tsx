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
      <aside className="self-start rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-sm lg:sticky lg:top-[calc(72px+3rem)]">
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
    template: "%s | Docs",
  },
};

export const revalidate = 300;

export default function DocsLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="mx-auto grid max-w-7xl gap-8 px-4 py-12 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] lg:grid-cols-[minmax(240px,0.4fr)_minmax(360px,0.6fr)]">
      <DocsNavPanel />
      <article className="flex-1 rounded-2xl border border-white/10 bg-slate-950/60 p-5 text-[15px] leading-7 text-slate-200 shadow-[0_35px_80px_rgba(1,3,20,0.55)] sm:p-8 [&>div]:space-y-10 [&_h1]:text-3xl [&_h1]:font-semibold [&_h1]:text-white [&_h1]:sm:text-4xl [&_h2]:text-2xl [&_h2]:font-semibold [&_h2]:text-white [&_h3]:text-lg [&_h3]:font-semibold [&_h3]:text-white [&_p]:text-slate-300 [&_ul]:text-slate-200 [&_ol]:text-slate-200">
        <div>{children}</div>
      </article>
    </div>
  );
}
