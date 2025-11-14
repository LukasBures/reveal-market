import "@testing-library/jest-dom/vitest";
import React from "react";
import { vi } from "vitest";

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    children,
    prefetch,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
    target?: string;
    rel?: string;
    prefetch?: boolean;
  }) => <a {...props}>{children}</a>,
}));

vi.mock("next/image", () => ({
  __esModule: true,
  default: ({ fill, priority, ...props }: React.ComponentProps<"img"> & { fill?: boolean; priority?: boolean }) => (
    <img {...props} data-fill={fill ? "true" : undefined} data-priority={priority ? "true" : undefined} />
  ),
}));
