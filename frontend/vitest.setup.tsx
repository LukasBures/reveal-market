import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, beforeEach, vi } from "vitest";

const stripLocalStorageFlag = (args: string[]) => {
  if (!Array.isArray(args) || args.length === 0) return;
  const cleaned: string[] = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--localstorage-file") {
      i += 1;
      continue;
    }
    if (arg.startsWith("--localstorage-file=")) {
      continue;
    }
    cleaned.push(arg);
  }
  if (cleaned.length !== args.length) {
    args.splice(0, args.length, ...cleaned);
  }
};

stripLocalStorageFlag(process.argv);
stripLocalStorageFlag(process.execArgv);

const originalEmitWarning = process.emitWarning.bind(process);
process.emitWarning = ((warning: string | Error, ...args: any[]) => {
  const message = typeof warning === "string" ? warning : warning?.message;
  if (typeof message === "string" && message.includes("--localstorage-file")) {
    return;
  }
  return originalEmitWarning(warning as any, ...args as any);
}) as typeof process.emitWarning;

if (!process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID) {
  process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID = "test-wc-project-id";
}

if (typeof window !== "undefined") {
  try {
    if (window.location?.href === "about:blank") {
      window.location.href = "https://revealmarket.xyz/";
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
  default: React.forwardRef<
    HTMLAnchorElement,
    {
      children: React.ReactNode;
      href: string;
      className?: string;
      target?: string;
      rel?: string;
      prefetch?: boolean;
      onClick?: React.MouseEventHandler<HTMLAnchorElement>;
    }
  >(({ children, prefetch, ...props }, ref) => (
    <a ref={ref} {...props}>
      {children}
    </a>
  )),
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

vi.mock("@/lib/wagmi", () => ({
  wagmiConfig: {},
}));

vi.mock("wagmi", () => {
  const noop = vi.fn();
  return {
    WagmiProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    useConnection: () => ({ address: undefined, chain: undefined, connector: undefined, status: "disconnected" }),
    useChainId: () => 26514,
    useConnect: () => ({ mutate: noop, status: "idle", error: null }),
    useConnectors: () => [],
    useDisconnect: () => ({ mutate: noop }),
    useSignMessage: () => ({ data: null, error: null, isPending: false, mutateAsync: noop }),
    useSwitchChain: () => ({ error: null, isPending: false, mutate: noop, mutateAsync: noop }),
    useWriteContract: () => ({ mutateAsync: noop, isPending: false, error: null }),
    useConfig: () => ({}),
  };
});

const defaultFetchMock = vi.fn(async () => ({
  ok: true,
  status: 200,
  json: async () => [],
}));

Object.defineProperty(globalThis, "fetch", {
  value: defaultFetchMock,
  writable: true,
});

beforeEach(() => {
  defaultFetchMock.mockClear();
});

afterEach(() => {
  defaultFetchMock.mockClear();
});
