import React from "react";
import { render, screen } from "@testing-library/react";
import { DocsNav } from "@/components/docs/DocsNav";
import { vi } from "vitest";

type MockUsePathname = () => string;

const usePathnameMock = vi.hoisted(() => vi.fn<MockUsePathname>(() => "/docs"));

vi.mock("next/navigation", () => {
  return {
    usePathname: usePathnameMock,
  };
});

describe("DocsNav", () => {
  beforeEach(() => {
    usePathnameMock.mockReset();
    usePathnameMock.mockReturnValue("/docs");
  });

  it("highlights the current route and renders expected links", () => {
    render(<DocsNav />);

    const overviewLink = screen.getByRole("link", { name: "Overview" });
    const gettingStartedLink = screen.getByRole("link", { name: "Getting Started" });
    const faqLink = screen.getByRole("link", { name: "FAQ" });

    expect(overviewLink).toHaveAttribute("href", "/docs");
    expect(gettingStartedLink).toHaveAttribute("href", "/docs/getting-started");
    expect(faqLink).toHaveAttribute("href", "/docs/faq");

    expect(overviewLink).toHaveClass("bg-white/15");
    expect(screen.getByText("Start Here")).toBeInTheDocument();
  });

  it("updates the active section based on the current pathname", () => {
    usePathnameMock.mockReturnValue("/docs/getting-started");
    render(<DocsNav />);

    expect(screen.getByRole("link", { name: "Getting Started" })).toHaveClass("bg-white/15");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveClass("bg-white/15");
  });
});
