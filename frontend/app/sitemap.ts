import type { MetadataRoute } from "next";
import { DEFAULT_API_BASE } from "@/lib/api";
import { categorySlugs, tagSlugs } from "@/lib/slugs";

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://revealmarket.xyz";

const DOC_PATHS = [
  "/docs",
  "/docs/manifesto",
  "/docs/the-story",
  "/docs/getting-started",
  "/docs/architecture",
  "/docs/core-infrastructure",
  "/docs/privacy-security",
  "/docs/integrations",
  "/docs/marketplace",
  "/docs/tokenomics",
  "/docs/tiers-fees",
  "/docs/referrals",
  "/docs/faq",
];

const STATIC_PATHS = ["/", "/about", "/legal", "/terms", "/privacy", "/cookies", "/disclaimer"];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date().toISOString();

  const createEntry = (
    path: string,
    priority = 0.7,
    changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"] = "weekly",
    lastModified = now,
  ): MetadataRoute.Sitemap[number] => ({
    url: `${BASE_URL}${path}`,
    lastModified,
    changeFrequency,
    priority,
  });

  const entries: MetadataRoute.Sitemap = [
    createEntry("/", 1, "daily"),
    ...STATIC_PATHS.filter((path) => path !== "/").map((path) => createEntry(path, 0.8)),
    ...DOC_PATHS.map((path) => createEntry(path, path === "/docs" ? 0.75 : 0.6)),
    ...categorySlugs.map((slug) => createEntry(`/categories/${slug}`, 0.7, "weekly")),
    ...tagSlugs.map((slug) => createEntry(`/tags/${slug}`, 0.65, "weekly")),
  ];

  try {
    const response = await fetch(`${DEFAULT_API_BASE}/markets?limit=200`, {
      next: { revalidate: 60 * 30 },
    });
    if (response.ok) {
      const payload = await response.json();
      if (Array.isArray(payload)) {
        entries.push(
          ...payload
            .filter((market) => typeof market?.event_id === "string")
            .map((market) =>
              createEntry(
                `/markets/${market.event_id}`,
                0.9,
                "hourly",
                market.updated_at ?? market.updatedAt ?? now,
              ),
            ),
        );
      }
    }
  } catch (error) {
    console.error("Failed to build dynamic sitemap entries", error);
  }

  return entries;
}
