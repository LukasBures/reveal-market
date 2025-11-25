import selectors from "../../contracts/cache/errors.json";

// errors.json maps selector -> signature (e.g., {"0x0dc149f0":"AlreadyInitialized()"})
const selectorMap: Record<string, string> = selectors as Record<string, string>;

export function decodeErrorSelector(data: string): string | null {
  if (!data || typeof data !== "string" || data.length < 10) return null;
  const selector = data.slice(0, 10).toLowerCase();
  return selectorMap[selector] ?? null;
}
