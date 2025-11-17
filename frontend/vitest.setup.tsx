import "@testing-library/jest-dom/vitest";
import React from "react";
import { vi } from "vitest";

if (typeof window !== "undefined") {
  try {
    if (window.location?.href === "about:blank") {
      window.location.href = "http://localhost:3000/";
    }
  } catch {
    // happy-dom may throw for read-only location; ignore in tests
  }

  const storage = new Map<string, string>();
  const storageShim: Storage = {
    get length() {
      return storage.size;
    },
    clear() {
      storage.clear();
    },
    getItem(key: string) {
      return storage.has(key) ? storage.get(key)! : null;
    },
    key(index: number) {
      return Array.from(storage.keys())[index] ?? null;
    },
    removeItem(key: string) {
      storage.delete(key);
    },
    setItem(key: string, value: string) {
      storage.set(key, value);
    },
  };

  if (typeof window.localStorage === "undefined" || typeof window.localStorage.getItem !== "function") {
    Object.defineProperty(window, "localStorage", {
      value: storageShim,
      writable: true,
    });
  }
}

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

vi.mock("next/font/google", () => ({
  Manrope: () => ({ className: "font-manrope", variable: "--font-sans" }),
}));

vi.mock("next/font/local", () => ({
  __esModule: true,
  default: () => ({ className: "font-local", variable: "--font-display" }),
}));

vi.mock("server-only", () => ({}));
