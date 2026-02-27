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
  datePublished,
  dateModified,
}: {
  title: string;
  description: string;
  path: string;
  image?: string;
  type?: "Article" | "TechArticle";
  datePublished?: string;
  dateModified?: string;
}): Record<string, any> {
  const payload: Record<string, any> = {
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
  if (datePublished) {
    payload.datePublished = datePublished;
  }
  if (dateModified) {
    payload.dateModified = dateModified;
  }
  return payload;
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
    title: "How Reveal Market Works: Private Prediction Flow Guide",
    description:
      "Learn the Reveal Market flow: access, request a quote, commit privately, then verify outcomes with settlement receipts and claim payouts after resolution.",
    keywords: [
      "reveal market overview",
      "prediction market docs",
      "how it works",
      "commit reveal",
    ],
  },
  "getting-started": {
    title: "Start Trading on Reveal Market: Access, Quote, Commit",
    description:
      "Get access, connect a wallet, request a signed quote, commit a ticket, and claim after settlement. A quick start guide for new participants ready to begin.",
    keywords: ["getting started", "commit", "claim", "settlement"],
  },
  "privacy-security": {
    title: "Privacy & Security in Reveal Market | Private Commits",
    description:
      "Reveal Market keeps participation private during live markets and publishes settlement receipts after resolution so outcomes and payouts stay transparent.",
    keywords: ["private commits", "settlement receipts", "privacy", "security"],
  },
  faq: {
    title: "Reveal Market FAQ: Participation, Settlement, Claims",
    description:
      "Quick answers on participation, quotes, settlement receipts, and claims so you can trade private prediction markets with confidence and clarity every day.",
    keywords: ["faq", "settlement", "claims", "how it works"],
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
