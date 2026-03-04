import { notFound } from "next/navigation";
import { Suspense } from "react";
import { FeaturedEventsSection, FeaturedEventsSkeleton } from "@/components/markets/FeaturedMarketsSection";
import { buildMetadata } from "@/lib/seo";

const CATEGORY_PAGES: Record<string, { label: string; apiLabel: string; title: string; description: string }> = {
  politics: {
    label: "Politics",
    apiLabel: "Politics",
    title: "Politics Prediction Markets",
    description:
      "Trade on elections, legislation, and political outcomes with private order flow and verified settlements.",
  },
  sports: {
    label: "Sports",
    apiLabel: "Sports",
    title: "Sports Prediction Markets",
    description: "Predict outcomes for NFL, NBA, soccer, UFC, and more with private order flow and verified payouts.",
  },
  crypto: {
    label: "Crypto",
    apiLabel: "Crypto",
    title: "Crypto Prediction Markets",
    description:
      "Trade on Bitcoin, Ethereum, DeFi, and blockchain events with private order flow and verified settlements.",
  },
  finance: {
    label: "Finance",
    apiLabel: "Finance",
    title: "Finance Prediction Markets",
    description:
      "Trade on stocks, bonds, earnings, and equity markets with private order flow and verified settlements.",
  },
  geopolitics: {
    label: "Geopolitics",
    apiLabel: "Geopolitics",
    title: "Geopolitics Prediction Markets",
    description:
      "Trade on global conflicts, sanctions, NATO, and international affairs with private order flow and verified payouts.",
  },
  economy: {
    label: "Economy",
    apiLabel: "Economy",
    title: "Economy Prediction Markets",
    description:
      "Trade on inflation, GDP, Fed rate decisions, and macroeconomic indicators with private order flow and verified settlements.",
  },
};

export const revalidate = 60;
export const dynamic = "force-dynamic";

export function generateStaticParams() {
  return Object.keys(CATEGORY_PAGES).map((category) => ({ category }));
}

export async function generateMetadata({ params }: { params: Promise<{ category: string }> }) {
  const { category } = await params;
  const config = CATEGORY_PAGES[category];
  if (!config) return {};
  return buildMetadata({ title: config.title, description: config.description, path: `/${category}` });
}

type PageProps = {
  params: Promise<{ category: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function CategoryPage({ params, searchParams }: PageProps) {
  const { category } = await params;
  const config = CATEGORY_PAGES[category];
  if (!config) notFound();
  const resolvedParams = (await searchParams) ?? {};
  const rawSort = typeof resolvedParams.sort === "string" ? resolvedParams.sort : undefined;
  const sortBy = (() => {
    if (rawSort === "newest") return "recent" as const;
    if (rawSort === "trending") return "popularity" as const;
    return "totalVolume" as const;
  })();
  return (
    <div className="mx-auto max-w-7xl px-4 pt-4 pb-16 text-white pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]">
      <h1 className="sr-only">{config.title}</h1>
      <Suspense fallback={<FeaturedEventsSkeleton />}>
        <FeaturedEventsSection categoryFilter={config.apiLabel} sortBy={sortBy} closesWithinHours={24} />
      </Suspense>
    </div>
  );
}
