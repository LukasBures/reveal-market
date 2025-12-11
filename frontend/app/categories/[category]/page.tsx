import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { buildBreadcrumbJsonLd, buildMetadata } from "@/lib/seo";
import { parseCategorySlug } from "@/lib/slugs";
import { CategoryMarkets } from "@/app/categories/[category]/CategoryMarkets";
import { MarketGridSkeleton } from "@/components/markets/MarketGridSkeleton";
import { JsonLd } from "@/components/seo/JsonLd";

export const dynamic = "force-dynamic";

type CategoryPageProps = {
  params: Promise<{ category: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

const resolvePageNumber = (searchParams: Record<string, string | string[] | undefined>): number => {
  const rawPage = searchParams.page ?? searchParams.p ?? null;
  const candidate = Array.isArray(rawPage) ? rawPage[0] : rawPage;
  const parsed = candidate ? Number.parseInt(candidate, 10) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
};

export async function generateMetadata({ params, searchParams }: CategoryPageProps): Promise<Metadata> {
  const { category } = await params;
  const pageNumber = resolvePageNumber((await searchParams) ?? {});
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
    keywords: [parsed.label, `${parsed.label} prediction markets`, "market categories"],
    robots: pageNumber > 1 ? { index: false, follow: true } : undefined,
  });
}

export default async function CategoryPage({ params }: CategoryPageProps) {
  const { category } = await params;
  const parsed = parseCategorySlug(category);
  if (!parsed) {
    notFound();
  }
  const breadcrumbs = buildBreadcrumbJsonLd([
    { name: "Home", path: "/" },
    { name: "Categories", path: "/categories" },
    { name: parsed.label, path: `/categories/${parsed.slug}` },
  ]);
  return (
    <>
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-8 text-white md:gap-10">
        <header className="space-y-3">
          <p className="text-xs uppercase tracking-[0.35em] text-slate-500">{parsed.label} markets</p>
          <h1 className="text-3xl font-semibold text-white">{parsed.label} prediction markets</h1>
          <p className="max-w-3xl text-slate-300">
            Explore live {parsed.label.toLowerCase()} markets with private commits, transparent settlement receipts, and deep
            liquidity. Results stay cached and indexable so you can monitor outcomes over time.
          </p>
        </header>
        <Suspense fallback={<MarketGridSkeleton />}>
          <CategoryMarkets slug={parsed.slug} />
        </Suspense>
      </div>
      <JsonLd data={breadcrumbs} id="category-breadcrumbs" />
    </>
  );
}
