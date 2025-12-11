import type { MetadataRoute } from "next";
import { resolveUrlConfig } from "@/lib/env-presets";

const { siteUrl } = resolveUrlConfig();
const DISALLOW = [
  "/api",
  "/api/*",
  "/app/api",
  "/app/api/*",
  "/healthz",
  "/health",
  "/api/health",
  "/app/api/health",
  "/_next",
  "/_next/*",
];

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: DISALLOW,
      },
    ],
    sitemap: [`${siteUrl}/sitemap.xml`],
    host: new URL(siteUrl).host,
  };
}
