import { describe, expect, it } from "vitest";
import {
  categorySlugFromLabel,
  parseCategorySlug,
  parseTagSlug,
  tagSlugFromLabel,
} from "@/lib/slugs";

describe("slug helpers", () => {
  it("converts category labels to canonical slugs", () => {
    expect(categorySlugFromLabel("AI & Tech")).toBe("ai-tech");
    expect(categorySlugFromLabel("Unknown")).toBeNull();
  });

  it("parses category slugs back into labels", () => {
    const parsed = parseCategorySlug("AI-Tech");
    expect(parsed).not.toBeNull();
    expect(parsed?.slug).toBe("ai-tech");
    expect(parsed?.label).toBe("AI & Tech");
  });

  it("parses tag slugs into labels", () => {
    const parsed = parseTagSlug("btc-halving");
    expect(parsed?.label).toBe("BTC halving");
  });

  it("returns null for unknown tag", () => {
    expect(parseTagSlug("nonexistent")).toBeNull();
    expect(tagSlugFromLabel("Nonexistent")).toBeNull();
  });
});
