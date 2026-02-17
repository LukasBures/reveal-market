import { DEFAULT_API_BASE } from "@/lib/api";
import { resolveUrlConfig } from "@/lib/env-presets";

export const revalidate = 3600;

const EVENT_PAGE_SIZE = 1000;

async function countEventPages(apiBase: string): Promise<number> {
  const url = new URL("/events/count", apiBase);
  url.searchParams.set("status", "any");

  try {
    const response = await fetch(url.toString(), {
      cache: "force-cache",
      next: { revalidate },
    });
    if (!response.ok) {
      return 0;
    }
    const payload = await response.json();
    const total = Number(payload?.total ?? 0);
    if (!Number.isFinite(total) || total <= 0) {
      return 0;
    }
    return Math.max(1, Math.ceil(total / EVENT_PAGE_SIZE));
  } catch {
    return 0;
  }
}

export async function GET(): Promise<Response> {
  const { siteUrl, apiBaseInternal } = resolveUrlConfig();
  const apiBase = (apiBaseInternal || DEFAULT_API_BASE).replace(/\/$/, "");
  const eventPages = await countEventPages(apiBase);

  const urls = [`${siteUrl}/sitemap-pages.xml`];
  for (let page = 1; page <= eventPages; page += 1) {
    urls.push(`${siteUrl}/sitemap-events.xml?page=${page}`);
  }

  const now = new Date().toISOString();
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls
  .map((url) => `  <sitemap><loc>${url}</loc><lastmod>${now}</lastmod></sitemap>`)
  .join("\n")}
</sitemapindex>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/xml",
    },
  });
}
