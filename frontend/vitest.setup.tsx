import "@testing-library/jest-dom/vitest";
import React from "react";
import { vi } from "vitest";

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    children,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
    target?: string;
    rel?: string;
  }) => <a {...props}>{children}</a>,
}));

vi.mock("next/image", () => ({
  __esModule: true,
  default: (props: React.ComponentProps<"img">) => <img {...props} />,
}));
