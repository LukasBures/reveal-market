// Minimal localStorage shim for SSR/dev environments where Node may expose an invalid
// globalThis.localStorage (e.g., misconfigured --localstorage-file). Ensures downstream
// SDKs that expect getItem/setItem do not crash.
export function ensureLocalStorage() {
  const ls: any = globalThis.localStorage as any;
  if (ls && typeof ls.getItem === "function" && typeof ls.setItem === "function") {
    return;
  }

  const store = new Map<string, string>();
  const polyfill = {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  } satisfies Storage;

  try {
    Object.defineProperty(globalThis, "localStorage", {
      value: polyfill,
      writable: false,
      configurable: true,
    });
  } catch {
    (globalThis as any).localStorage = polyfill;
  }
}
