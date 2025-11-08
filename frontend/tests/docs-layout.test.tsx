import React from "react";
import { render, screen } from "@testing-library/react";
import DocsLayout from "@/app/docs/layout";

describe("DocsLayout", () => {
  it("wraps children and renders navigation", () => {
    const childText = "Investor-grade docs";
    render(
      <DocsLayout>
        <p>{childText}</p>
      </DocsLayout>
    );

    expect(screen.getByText("Documentation")).toBeInTheDocument();
    expect(screen.getByText(childText)).toBeInTheDocument();
  });
});
