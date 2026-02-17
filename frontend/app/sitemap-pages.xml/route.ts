import type { MetadataRoute } from "next";
import { resolveUrlConfig } from "@/lib/env-presets";

export const revalidate = 3600;

const DOC_PATHS = [
  "/docs",
  "/docs/getting-started",
  "/docs/privacy-security",
  "/docs/faq",
];

const STATIC_PATHS = ["/", "/about", "/contact", "/legal", "/terms", "/privacy", "/cookies", "/disclaimer", "/proofs"];

const renderSitemap = (entries: MetadataRoute.Sitemap): string => {
  const body = entries
    .map((entry) => {
      const lastModified = entry.lastModified ? `<lastmod>${entry.lastModified}</lastmod>` : "";
      const changeFrequency = entry.changeFrequency ? `<changefreq>${entry.changeFrequency}</changefreq>` : "";
      const priority = entry.priority !== undefined ? `<priority>${entry.priority}</priority>` : "";
      return `  <url><loc>${entry.url}</loc>${lastModified}${changeFrequency}${priority}</url>`;
    })
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>`;
};

export async function GET(): Promise<Response> {
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

  const entries: MetadataRoute.Sitemap = [
    createEntry("/", 1, "daily"),
    ...STATIC_PATHS.filter((path) => path !== "/").map((path) => createEntry(path, 0.8)),
    ...DOC_PATHS.map((path) => createEntry(path, path === "/docs" ? 0.75 : 0.6)),
  ];

  return new Response(renderSitemap(entries), {
    headers: {
      "Content-Type": "application/xml",
    },
  });
}
