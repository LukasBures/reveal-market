import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { buildMetadata } from "@/lib/seo";
import { parseTagSlug, tagSlugs } from "@/lib/slugs";
import { TagMarkets } from "@/app/tags/[tag]/TagMarkets";
import { MarketGridSkeleton } from "@/components/markets/MarketGridSkeleton";

type TagPageProps = {
  params: Promise<{ tag: string }>;
};

export function generateStaticParams() {
  return tagSlugs.map((tag) => ({ tag }));
}

export async function generateMetadata({ params }: TagPageProps): Promise<Metadata> {
  const { tag } = await params;
  const parsed = parseTagSlug(tag);
  if (!parsed) {
    return buildMetadata({ title: "Tags | Reveal Market", description: "Explore tagged markets.", path: "/tags" });
  }
  return buildMetadata({
    title: `#${parsed.label} Markets | Reveal Market`,
    description: `Live prediction markets tagged ${parsed.label}.`,
    path: `/tags/${parsed.slug}`,
  });
}

export default async function TagPage({ params }: TagPageProps) {
  const { tag } = await params;
  const parsed = parseTagSlug(tag);
  if (!parsed) {
    notFound();
  }
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-white">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Tagged Markets</p>
        <h1 className="text-3xl font-semibold">#{parsed!.label}</h1>
        <p className="text-slate-400">
          Mirror of live markets that include the “{parsed!.label}” tag. Use the filters to pivot into other narratives.
        </p>
      </div>
      <Suspense fallback={<MarketGridSkeleton />}>
        <TagMarkets slug={parsed!.slug} />
      </Suspense>
    </div>
  );
}
