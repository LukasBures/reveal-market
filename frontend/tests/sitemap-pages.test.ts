import { describe, expect, it } from "vitest";
import { GET } from "@/app/sitemap-pages.xml/route";

const extractLocs = (xml: string) =>
  Array.from(xml.matchAll(/<loc>([^<]+)<\/loc>/g)).map((match) => match[1]);

const stubSiteUrl = () => {
  process.env.NEXT_PUBLIC_SITE_URL = "https://revealmarket.xyz";
};

describe("sitemap pages", () => {
  it("only includes existing docs routes", async () => {
    stubSiteUrl();
    const response = await GET();
    const xml = await response.text();
    const locs = extractLocs(xml);

    expect(locs).toContain("https://revealmarket.xyz/docs");
    expect(locs).toContain("https://revealmarket.xyz/docs/getting-started");
    expect(locs).toContain("https://revealmarket.xyz/docs/privacy-security");
    expect(locs).toContain("https://revealmarket.xyz/docs/faq");

    expect(locs).not.toContain("https://revealmarket.xyz/docs/manifesto");
    expect(locs).not.toContain("https://revealmarket.xyz/docs/the-story");
  });
});
