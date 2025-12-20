import type { MetadataRoute } from "next";
import { DEFAULT_API_BASE } from "@/lib/api";
import { resolveUrlConfig } from "@/lib/env-presets";
import { categorySlugs } from "@/lib/slugs";

const urls = resolveUrlConfig();
const BASE_URL = urls.siteUrl;
const API_BASE_OVERRIDE = (urls.apiBaseInternal || DEFAULT_API_BASE).replace(/\/$/, "");

const DOC_PATHS = [
  "/docs",
  "/docs/manifesto",
  "/docs/the-story",
  "/docs/getting-started",
  "/docs/architecture",
  "/docs/core-infrastructure",
  "/docs/roadmap",
  "/docs/privacy-security",
  "/docs/integrations",
  "/docs/marketplace",
  "/docs/tokenomics",
  "/docs/tiers-fees",
  "/docs/referrals",
  "/docs/faq",
  "/docs/api",
];

const STATIC_PATHS = ["/", "/about", "/contact", "/legal", "/terms", "/privacy", "/cookies", "/disclaimer", "/proofs"];

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
  ];

  const pushMarketEntries = (markets: any[]) => {
    entries.push(
      ...markets
        .filter((market) => typeof (market?.event_id ?? market?.eventId) === "string")
        .map((market) =>
          createEntry(
            `/markets/${market.event_id ?? market.eventId}`,
            0.9,
            "hourly",
            market.updated_at ?? market.updatedAt ?? now,
          ),
        ),
    );
  };

  const candidates = Array.from(
    new Set(
      [
        API_BASE_OVERRIDE,
        urls.apiBaseUrl?.replace(/\/$/, ""),
        DEFAULT_API_BASE.replace(/\/$/, ""),
        process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, ""),
        "http://localhost:8000",
        "http://api.localhost",
      ].filter(Boolean) as string[],
    ),
  );

  for (const base of candidates) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 3000);
      const response = await fetch(`${base}/markets?limit=200`, {
        next: { revalidate: 60 * 30 },
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!response.ok) {
        console.warn("Sitemap markets fetch returned non-200", response.status, base);
        continue;
      }
      const payload = await response.json();
      const markets = Array.isArray(payload) ? payload : payload?.items ?? [];
      pushMarketEntries(markets);
      break;
    } catch (error) {
      console.warn("Failed to build dynamic sitemap entries", base, error);
    }
  }

  return entries;
}
