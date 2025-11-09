import type { MetadataRoute } from "next";

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

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date().toISOString();

  const makeEntry = (path: string, priority = 0.7): MetadataRoute.Sitemap[number] => ({
    url: `${BASE_URL}${path}`,
    lastModified: now,
    changeFrequency: "weekly",
    priority,
  });

  return [
    makeEntry("/", 1),
    ...STATIC_PATHS.filter((path) => path !== "/").map((path) => makeEntry(path, 0.8)),
    ...DOC_PATHS.map((path) => makeEntry(path, path === "/docs" ? 0.8 : 0.6)),
  ];
}
