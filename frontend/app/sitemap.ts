import type { MetadataRoute } from "next";
import { DEFAULT_API_BASE } from "@/lib/api";
import { resolveUrlConfig } from "@/lib/env-presets";
import { categorySlugs } from "@/lib/slugs";

export const revalidate = 3600;

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

  return entries;
}
