import type { MetadataRoute } from "next";
import { resolveUrlConfig } from "@/lib/env-presets";

export const revalidate = 3600;

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

export default function sitemap(): MetadataRoute.Sitemap {
  const { siteUrl } = resolveUrlConfig();
  const now = new Date().toISOString();

  const createEntry = (
    path: string,
    priority = 0.7,
    changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"] = "weekly",
    lastModified = now,
  ): MetadataRoute.Sitemap[number] => ({
    url: `${siteUrl}${path}`,
    lastModified,
    changeFrequency,
    priority,
  });

  return [
    createEntry("/", 1, "daily"),
    ...STATIC_PATHS.filter((path) => path !== "/").map((path) => createEntry(path, 0.8)),
    ...DOC_PATHS.map((path) => createEntry(path, path === "/docs" ? 0.75 : 0.6)),
  ];
}
