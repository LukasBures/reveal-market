import type { Metadata } from "next";
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
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-12 lg:flex-row">
      <DocsNav />
      <article className="flex-1 space-y-6 rounded-2xl border border-white/10 bg-slate-950/60 p-6 text-slate-200">
        <div>{children}</div>
      </article>
    </div>
  );
}
