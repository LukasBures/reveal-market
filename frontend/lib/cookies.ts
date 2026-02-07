export function getCookieValue(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const raw = document.cookie;
  if (!raw) return null;
  const parts = raw.split("; ");
  for (const part of parts) {
    if (!part) continue;
    const [key, ...rest] = part.split("=");
    if (key === name) {
      return decodeURIComponent(rest.join("="));
    }
  }
  return null;
}
