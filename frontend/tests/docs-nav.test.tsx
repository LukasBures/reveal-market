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

    expect(screen.getByText("Overview")).toHaveClass("bg-white/15");
    expect(screen.getByText("Marketplace")).toHaveClass("text-slate-400");

    const categories = screen.getAllByText(/Foundation|Platform|Economy/);
    expect(categories).toHaveLength(3);
  });
});
