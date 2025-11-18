const CATEGORY_MAP: Record<string, string> = {
  'trending': 'Trending',
  'breaking': 'Breaking',
  'new': 'New',
  'politics': 'Politics',
  'sports': 'Sports',
  'finance': 'Finance',
  'crypto': 'Crypto',
  'geopolitics': 'Geopolitics',
  'earnings': 'Earnings',
  'tech': 'Tech',
  'culture': 'Culture',
  'world': 'World',
  'economy': 'Economy',
  'elections': 'Elections',
  'mentions': 'Mentions',
};

export const categoryLabels = Object.values(CATEGORY_MAP);
export const categorySlugs = Object.keys(CATEGORY_MAP);

export function slugify(value: string): string {
  return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '-');
}

export function parseCategorySlug(input: string): { slug: string; label: string } | null {
  const slug = slugify(input);
  const label = CATEGORY_MAP[slug];
  if (!label) {
    return null;
  }
  return { slug, label };
}

export function categorySlugFromLabel(label: string): string | null {
  const slug = slugify(label);
  return CATEGORY_MAP[slug] ? slug : null;
}

export function categoryLabelFromSlug(slug: string): string | null {
  return CATEGORY_MAP[slug] ?? null;
}
