import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { buildMetadata } from "@/lib/seo";
import { parseCategorySlug } from "@/lib/slugs";
import { CategoryMarkets } from "@/app/categories/[category]/CategoryMarkets";
import { MarketGridSkeleton } from "@/components/markets/MarketGridSkeleton";

export const dynamic = "force-dynamic";

type CategoryPageProps = {
  params: Promise<{ category: string }>;
};

export async function generateMetadata({ params }: CategoryPageProps): Promise<Metadata> {
  const { category } = await params;
  const parsed = parseCategorySlug(category);
  if (!parsed) {
    return buildMetadata({
      title: "Categories | Reveal Market",
      description: "Explore curated market categories.",
      path: "/categories",
    });
  }
  return buildMetadata({
    title: `${parsed.label} Markets | Reveal Market`,
    description: `Live prediction markets categorized under ${parsed.label}.`,
    path: `/categories/${parsed.slug}`,
  });
}

export default async function CategoryPage({ params }: CategoryPageProps) {
  const { category } = await params;
  const parsed = parseCategorySlug(category);
  if (!parsed) {
    notFound();
  }
  const label = parsed!.label;
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-12 text-white md:gap-10">
      <section className="glass-panel relative overflow-hidden px-4 py-8 sm:px-6 md:px-10">
        <div className="pointer-events-none absolute -right-10 top-0 h-48 w-48 rounded-full bg-brand-400/20 blur-3xl" />
        <p className="text-center text-xs uppercase tracking-[0.35em] text-slate-400 md:text-left">Category</p>
        <div className="mt-3 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="space-y-3 text-center md:text-left">
            <h1 className="text-3xl font-semibold md:text-4xl">{label}</h1>
            <p className="text-base text-slate-300 md:max-w-2xl">
              Live markets classified under “{label}”. You’ll see up to sixty of the freshest markets mirrored from the
              worker feed; if the feed is still syncing we backfill with featured liquidity so the page never feels empty.
            </p>
          </div>
        </div>
      </section>
      <Suspense fallback={<MarketGridSkeleton />}>
        <CategoryMarkets slug={parsed!.slug} />
      </Suspense>
    </div>
  );
}
