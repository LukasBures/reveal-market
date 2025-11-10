import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { buildMetadata } from "@/lib/seo";
import { categorySlugs, parseCategorySlug } from "@/lib/slugs";
import { CategoryMarkets } from "@/app/categories/[category]/CategoryMarkets";
import { MarketGridSkeleton } from "@/components/markets/MarketGridSkeleton";

type CategoryPageProps = {
  params: Promise<{ category: string }>;
};

export function generateStaticParams() {
  return categorySlugs.map((category) => ({ category }));
}

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
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-white">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Category</p>
        <h1 className="text-3xl font-semibold">{label}</h1>
        <p className="text-slate-400">
          Live markets classified under “{label}”. Use the search bar or quick tags to pivot to other narratives.
        </p>
      </div>
      <Suspense fallback={<MarketGridSkeleton />}>
        <CategoryMarkets slug={parsed!.slug} />
      </Suspense>
    </div>
  );
}
