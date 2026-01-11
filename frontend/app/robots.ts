import type { MetadataRoute } from "next";
import { resolveUrlConfig } from "@/lib/env-presets";

export const revalidate = 3600;

const { siteUrl } = resolveUrlConfig();
const DISALLOW = [
  "/api",
  "/api/*",
  "/app/api",
  "/app/api/*",
  "/healthz",
  "/api/healthz",
  "/app/api/healthz",
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
