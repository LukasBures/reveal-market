import React from "react";
import { render, screen } from "@testing-library/react";
import { MainNav } from "@/components/layout/MainNav";

describe("MainNav", () => {
  it("links the brand to the homepage", () => {
    render(<MainNav />);
    expect(screen.getByRole("link", { name: /reveal market/i })).toHaveAttribute("href", "/");
  });

  it("shows only the Log In CTA", () => {
    render(<MainNav />);

    expect(screen.getByRole("link", { name: /log in/i })).toHaveAttribute("href", "/login");
    expect(screen.queryByText("Markets")).not.toBeInTheDocument();
    expect(screen.queryByText("About")).not.toBeInTheDocument();
    expect(screen.queryByText("Docs")).not.toBeInTheDocument();
  });
});
