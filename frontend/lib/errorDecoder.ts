import errors from "../../contracts/cache/errors.json";

// Map selector (0x12345678) to error name
const selectorMap: Record<string, string> = errors as Record<string, string>;

export function decodeErrorSelector(data: string): string | null {
  if (!data || typeof data !== "string" || data.length < 10) return null;
  const selector = data.slice(0, 10).toLowerCase();
  const entry = Object.entries(selectorMap).find(([, sel]) => sel.toLowerCase() === selector);
  return entry ? entry[0] : null;
}
