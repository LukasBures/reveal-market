import { describe, expect, it } from "vitest";
import { categorySlugFromLabel, parseCategorySlug } from "@/lib/slugs";

describe("slug helpers", () => {
  it("converts category labels to canonical slugs", () => {
    expect(categorySlugFromLabel("Tech")).toBe("ai-tech");
    expect(categorySlugFromLabel("Unknown")).toBeNull();
  });

  it("parses category slugs back into labels", () => {
    const parsed = parseCategorySlug("AI-Tech");
    expect(parsed).not.toBeNull();
    expect(parsed?.slug).toBe("ai-tech");
    expect(parsed?.label).toBe("Tech");
  });

  it("returns null for unknown category slug", () => {
    expect(parseCategorySlug("nonexistent")).toBeNull();
  });
});
