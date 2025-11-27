import React from "react";
import { render, screen } from "@testing-library/react";
import { DocsNav } from "@/components/docs/DocsNav";
import { vi } from "vitest";

type MockUsePathname = () => string;

vi.mock("next/navigation", () => {
  return {
    usePathname: vi.fn<MockUsePathname>(() => "/docs"),
  };
});

describe("DocsNav", () => {
  it("highlights the current route and renders all sections", () => {
    render(<DocsNav />);

    expect(screen.getByText("Investor Overview")).toHaveClass("bg-white/15");
    expect(screen.getByText("Execution Roadmap")).toBeInTheDocument();

    ["Vision", "Roadmap", "Tokenomics", "Infrastructure", "Legal & FAQ"].forEach((label) => {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    });

    expect(screen.getByRole("link", { name: /Connect With The Team/i })).toHaveAttribute("href", "/contact");
  });
});
