const CATEGORY_MAP: Record<string, string> = {
  trending: "Trending",
  breaking: "Breaking",
  new: "New",
  crypto: "Crypto",
  finance: "Finance",
  sports: "Sports",
  politics: "Politics",
  geopolitics: "Geopolitics",
  "ai-tech": "Tech",
  entertainment: "Entertainment",
  elections: "Elections",
  science: "Science",
  earnings: "Earnings",
  culture: "Culture",
  world: "World",
  economy: "Economy",
  mentions: "Mentions",
};

const CATEGORY_ALIASES: Record<string, string> = {
  tech: "ai-tech",
};

export const categoryLabels = Object.values(CATEGORY_MAP);
export const categorySlugs = Object.keys(CATEGORY_MAP);

export function slugify(value: string): string {
  return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "-");
}

export function parseCategorySlug(input: string): { slug: string; label: string } | null {
  const canonicalSlug = categorySlugFromLabel(input) ?? slugify(input);
  const label = CATEGORY_MAP[canonicalSlug];
  if (!label) {
    return null;
  }
  return { slug: canonicalSlug, label };
}

export function categorySlugFromLabel(label: string): string | null {
  const slug = slugify(label);
  if (CATEGORY_MAP[slug]) {
    return slug;
  }
  return CATEGORY_ALIASES[slug] ?? null;
}

export function categoryLabelFromSlug(slug: string): string | null {
  return CATEGORY_MAP[slug] ?? null;
}
