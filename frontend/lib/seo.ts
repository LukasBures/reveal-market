import type { Metadata } from "next";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://revealmarket.xyz";
const DEFAULT_IMAGE = "/opengraph-image";

export const absoluteUrl = (path = "/"): string => {
  try {
    return new URL(path, SITE_URL).toString();
  } catch {
    return `${SITE_URL.replace(/\/$/, "")}${path}`;
  }
};

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
  robots = {
    index: true,
    follow: true,
  },
}: MetadataOptions): Metadata {
  const canonical = absoluteUrl(path);
  const imageUrl = absoluteUrl(image);

  return {
    title,
    description,
    keywords,
    alternates: {
      canonical,
    },
    openGraph: {
      title,
      description,
      url: canonical,
      type,
      siteName: "Reveal Market",
      images: [{ url: imageUrl, width: 1200, height: 630, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      site: "@RevealMarket",
      creator: "@RevealMarket",
      title,
      description,
      images: [imageUrl],
    },
    robots,
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
  },
  "getting-started": {
    title: "Getting Started",
    description: "Integration checklist for exchanges, LPs, and teams onboarding to Reveal Market.",
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
  },
  integrations: {
    title: "Integration Playbook",
    description:
      "API surfaces, webhook concepts, and partner tooling for embedding Reveal Market feeds.",
  },
  marketplace: {
    title: "Marketplace Overview",
    description:
      "Market lifecycle, user experience goals, and custom storefront plans for partners.",
  },
  tokenomics: {
    title: "Tokenomics",
    description:
      "Fee capture, treasury flow, and token utility powering Reveal Market incentives.",
  },
  "tiers-fees": {
    title: "Tiers & Fees",
    description:
      "Breakdown of fee schedules, rake overrides, and performance incentives for partners.",
  },
  referrals: {
    title: "Referral Engine",
    description:
      "How referral cohorts, KPI options, and co-marketing programs reward distribution partners.",
  },
  faq: {
    title: "Reveal Market FAQ",
    description:
      "Answers to common diligence questions covering custody, compliance, and product ops.",
  },
  api: {
    title: "API Reference",
    description:
      "Details on REST endpoints, caching semantics, and rate-limits for Reveal Market APIs.",
  },
};

export function docsMetadata(slug: keyof typeof docsMeta): Metadata {
  const entry = docsMeta[slug];
  const path = slug === "overview" ? "/docs" : `/docs/${slug}`;
  return buildMetadata({
    title: entry.title,
    description: entry.description,
    path,
    keywords: entry.keywords,
    type: "article",
  });
}

export type DocsSlug = keyof typeof docsMeta;
