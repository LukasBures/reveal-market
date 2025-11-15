import React from "react";
import { render, screen } from "@testing-library/react";
import { MainNav } from "@/components/layout/MainNav";

describe("MainNav", () => {
  it("links the brand to the homepage", () => {
    render(<MainNav />);
    expect(screen.getByRole("link", { name: /reveal market/i })).toHaveAttribute("href", "/");
  });

  it("contains Docs + Log In calls to action", () => {
    render(<MainNav />);
    expect(screen.getByRole("link", { name: /docs/i })).toHaveAttribute("href", "/docs");
    expect(screen.getByRole("link", { name: /log in/i })).toHaveAttribute("href", "/login");
  });

  it("renders a static desktop navigation bar with two actions", () => {
    render(<MainNav />);
    const nav = screen.getByRole("navigation");
    expect(nav).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /menu/i })).not.toBeInTheDocument();
  });
});
