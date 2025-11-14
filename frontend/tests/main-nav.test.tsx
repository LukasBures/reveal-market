import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
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

  it("toggles the mobile menu button state", () => {
    render(<MainNav />);
    const toggle = screen.getByRole("button", { name: /menu/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
