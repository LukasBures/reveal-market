import type { Metadata } from "next";

import { resolveUrlConfig } from "@/lib/env-presets";

const SITE_NAME = "Reveal Market";
const { siteUrl: SITE_URL } = resolveUrlConfig();
const DEFAULT_IMAGE = "/opengraph-image";

export const absoluteUrl = (path = "/"): string => {
  try {
    return new URL(path, SITE_URL).toString();
  } catch {
    return `${SITE_URL.replace(/\/$/, "")}${path}`;
  }
};

const normalizeKeywords = (keywords: string[]): string[] => {
  const seen = new Set<string>();
  const unique: string[] = [];
  [...keywords, SITE_NAME].forEach((keyword) => {
    const trimmed = keyword.trim();
    if (!trimmed) return;
    const lowered = trimmed.toLowerCase();
    if (seen.has(lowered)) return;
    seen.add(lowered);
    unique.push(trimmed);
  });
  return unique;
};

const cleanTitle = (title: string): string =>
  title.trim().replace(new RegExp(`\\s*\\|\\s*${SITE_NAME}$`, "i"), "");

type RobotsMeta = Exclude<Metadata["robots"], string | null | undefined>;
type RobotsInfo = Omit<RobotsMeta, "googleBot">;

const DEFAULT_ROBOTS: RobotsMeta = {
  index: true,
  follow: true,
  "max-image-preview": "large",
  "max-snippet": -1,
  "max-video-preview": -1,
  googleBot: {
    index: true,
    follow: true,
    "max-image-preview": "large",
    "max-snippet": -1,
    "max-video-preview": -1,
  },
};

const mergeRobots = (robots?: Metadata["robots"]): Metadata["robots"] => {
  if (!robots) return DEFAULT_ROBOTS;
  if (typeof robots === "string") return robots;
  const merged: RobotsMeta = { ...DEFAULT_ROBOTS, ...robots };
  if (typeof robots.googleBot === "string") {
    merged.googleBot = robots.googleBot;
    return merged;
  }
  if (robots.googleBot) {
    merged.googleBot = {
      ...(typeof DEFAULT_ROBOTS.googleBot === "object" ? DEFAULT_ROBOTS.googleBot : {}),
      ...robots.googleBot,
    };
    return merged;
  }
  const mirrorKeys = [
    "index",
    "follow",
    "noarchive",
    "nosnippet",
    "noimageindex",
    "nocache",
    "notranslate",
    "indexifembedded",
    "nositelinkssearchbox",
    "unavailable_after",
    "max-video-preview",
    "max-image-preview",
    "max-snippet",
  ] as const satisfies ReadonlyArray<keyof RobotsInfo>;
  type MirrorKey = typeof mirrorKeys[number];
  const derivedGoogleBot: Partial<Record<MirrorKey, RobotsInfo[MirrorKey]>> = {
    ...(typeof DEFAULT_ROBOTS.googleBot === "object" ? DEFAULT_ROBOTS.googleBot : {}),
  };
  mirrorKeys.forEach((key) => {
    const value = robots[key] as RobotsInfo[MirrorKey] | undefined;
    if (typeof value !== "undefined") {
      derivedGoogleBot[key] = value;
    }
  });
  merged.googleBot = derivedGoogleBot as RobotsInfo;
  return merged;
};

export function buildBreadcrumbJsonLd(
  items: { name: string; path: string }[],
): Record<string, any> | null {
  if (!Array.isArray(items) || !items.length) {
    return null;
  }
  const list = items
    .map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.path),
    }))
    .filter((entry) => entry.name && entry.item);
  if (!list.length) {
    return null;
  }
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: list,
  };
}

export function buildFaqJsonLd(
  faqs: { question: string; answer: string }[],
  pagePath: string,
): Record<string, any> | null {
  if (!Array.isArray(faqs) || !faqs.length) {
    return null;
  }
  const mainEntity = faqs
    .map((faq) => ({
      "@type": "Question",
      name: faq.question,
      acceptedAnswer: {
        "@type": "Answer",
        text: faq.answer,
      },
    }))
    .filter((item) => item.name && item.acceptedAnswer?.text);
  if (!mainEntity.length) {
    return null;
  }
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity,
    url: absoluteUrl(pagePath),
  };
}

export function buildArticleJsonLd({
  title,
  description,
  path,
  image = DEFAULT_IMAGE,
  type = "Article",
}: {
  title: string;
  description: string;
  path: string;
  image?: string;
  type?: "Article" | "TechArticle";
}): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": type,
    headline: cleanTitle(title),
    description,
    url: absoluteUrl(path),
    image: [absoluteUrl(image)],
    inLanguage: "en",
    isAccessibleForFree: true,
    author: {
      "@type": "Organization",
      name: SITE_NAME,
      url: absoluteUrl("/"),
    },
    publisher: {
      "@type": "Organization",
      name: SITE_NAME,
      logo: {
        "@type": "ImageObject",
        url: absoluteUrl("/opengraph-image"),
      },
    },
  };
}

export function buildContactPageJsonLd(path: string): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "ContactPage",
    name: `${SITE_NAME} Contact`,
    url: absoluteUrl(path),
    mainEntityOfPage: absoluteUrl(path),
    publisher: {
      "@type": "Organization",
      name: SITE_NAME,
    },
  };
}

interface MetadataOptions {
  title: string;
  description: string;
  path?: string;
  keywords?: string[];
  image?: string;
  type?: "website" | "article";
  robots?: Metadata["robots"];
}

export function buildMetadata({
  title,
  description,
  path = "/",
  keywords = [],
  image = DEFAULT_IMAGE,
  type = "website",
  robots,
}: MetadataOptions): Metadata {
  const canonical = absoluteUrl(path);
  const imageUrl = absoluteUrl(image);
  const normalizedTitle = cleanTitle(title);
  const resolvedRobots = mergeRobots(robots);

  return {
    title: normalizedTitle,
    description,
    keywords: normalizeKeywords(keywords),
    alternates: {
      canonical,
    },
    openGraph: {
      title: normalizedTitle,
      description,
      url: canonical,
      type,
      siteName: SITE_NAME,
      images: [{ url: imageUrl, width: 1200, height: 630, alt: normalizedTitle }],
    },
    twitter: {
      card: "summary_large_image",
      site: "@RevealMarket",
      creator: "@RevealMarket",
      title: normalizedTitle,
      description,
      images: [imageUrl],
    },
    robots: resolvedRobots,
  };
}

const docsMeta: Record<
  string,
  { title: string; description: string; keywords?: string[] }
> = {
  overview: {
    title: "Reveal Market Docs Overview",
    description:
      "Investor briefing on the Reveal Market architecture, roadmap, and partner opportunities.",
    keywords: [
      "reveal market overview",
      "prediction market docs",
      "investor brief",
      "zk markets",
    ],
  },
  manifesto: {
    title: "Reveal Market Manifesto",
    description:
      "Principles guiding privacy-first prediction markets, institutional integrity, and zk-powered governance.",
    keywords: ["manifesto", "principles", "privacy", "institutions"],
  },
  "the-story": {
    title: "Reveal Market Story",
    description:
      "Milestones, adoption metrics, and roadmap for scaling Reveal Market across networks and partners.",
    keywords: ["growth timeline", "adoption milestones", "roadmap progress"],
  },
  "getting-started": {
    title: "Getting Started",
    description: "Integration checklist for exchanges, LPs, and teams onboarding to Reveal Market.",
    keywords: ["integration checklist", "partner onboarding", "api setup"],
  },
  architecture: {
    title: "Reveal Market Architecture",
    description:
      "Deep dive into the FastAPI service, ingestion worker, Redis layer, and Foundry contracts.",
    keywords: ["architecture", "fastapi", "redis", "worker"],
  },
  "core-infrastructure": {
    title: "Core Infrastructure",
    description:
      "Breakdown of backend systems, observability, migrations, and infrastructure dependencies.",
    keywords: ["infrastructure", "observability", "migrations", "dependencies"],
  },
  roadmap: {
    title: "Execution Roadmap",
    description:
      "Sequenced milestones across data assurance, liquidity automation, and compliance-ready launches.",
    keywords: ["roadmap", "milestones", "execution plan"],
  },
  "privacy-security": {
    title: "Privacy & Security",
    description:
      "Security posture, privacy guarantees, and operational controls that harden Reveal Market.",
    keywords: ["privacy controls", "security posture", "compliance"],
  },
  integrations: {
    title: "Integration Playbook",
    description:
      "API surfaces, webhook concepts, and partner tooling for embedding Reveal Market feeds.",
    keywords: ["webhooks", "api integrations", "partner tooling"],
  },
  marketplace: {
    title: "Marketplace Overview",
    description:
      "Market lifecycle, user experience goals, and custom storefront plans for partners.",
    keywords: ["market lifecycle", "storefront", "prediction market ux"],
  },
  tokenomics: {
    title: "Tokenomics",
    description:
      "Fee capture, treasury flow, and token utility powering Reveal Market incentives.",
    keywords: ["token utility", "treasury", "fee capture"],
  },
  "tiers-fees": {
    title: "Tiers & Fees",
    description:
      "Breakdown of fee schedules, rake overrides, and performance incentives for partners.",
    keywords: ["fee schedule", "rake", "incentives"],
  },
  referrals: {
    title: "Referral Engine",
    description:
      "How referral cohorts, KPI options, and co-marketing programs reward distribution partners.",
    keywords: ["referral program", "distribution", "co-marketing"],
  },
  faq: {
    title: "Reveal Market FAQ",
    description:
      "Answers to common diligence questions covering custody, compliance, and product ops.",
    keywords: ["faq", "diligence questions", "reveal market answers"],
  },
  api: {
    title: "API Reference",
    description:
      "Details on REST endpoints, caching semantics, and rate-limits for Reveal Market APIs.",
    keywords: ["api reference", "rest endpoints", "rate limits"],
  },
};

export type DocsSlug = keyof typeof docsMeta;

export const docsPath = (slug: DocsSlug): string => (slug === "overview" ? "/docs" : `/docs/${slug}`);

export const getDocsMeta = (slug: DocsSlug) => docsMeta[slug];

export function docsMetadata(slug: keyof typeof docsMeta): Metadata {
  const entry = docsMeta[slug];
  const path = docsPath(slug);
  return buildMetadata({
    title: entry.title,
    description: entry.description,
    path,
    keywords: entry.keywords,
    type: "article",
  });
}
