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
  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-8 text-white md:gap-10">
      <Suspense fallback={<MarketGridSkeleton />}>
        <CategoryMarkets slug={parsed!.slug} />
      </Suspense>
    </div>
  );
}
