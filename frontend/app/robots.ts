import type { MetadataRoute } from "next";
import { resolveUrlConfig } from "@/lib/env-presets";

const BASE_URL = resolveUrlConfig().siteUrl;

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
      },
    ],
    sitemap: [`${BASE_URL}/sitemap.xml`],
    host: BASE_URL,
  };
}
