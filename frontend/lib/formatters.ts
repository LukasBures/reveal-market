const DEFAULT_LOCALE = "en-US";
const DEFAULT_TIME_ZONE = "UTC";
const FALLBACK = "—";

const defaultNumberFormatter = new Intl.NumberFormat(DEFAULT_LOCALE);

export function formatNumber(value?: number | null, options?: Intl.NumberFormatOptions): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return FALLBACK;
  }
  if (!options) {
    return defaultNumberFormatter.format(value);
  }
  return new Intl.NumberFormat(DEFAULT_LOCALE, options).format(value);
}

export function formatUsd(
  value?: number | null,
  options?: Pick<Intl.NumberFormatOptions, "minimumFractionDigits" | "maximumFractionDigits">
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return FALLBACK;
  }
  const abs = Math.abs(value);
  const maximumFractionDigits =
    typeof options?.maximumFractionDigits === "number"
      ? options.maximumFractionDigits
      : abs >= 1000
        ? 0
        : abs >= 10
          ? 2
          : 4;
  const minimumFractionDigits = options?.minimumFractionDigits ?? 0;
  return new Intl.NumberFormat(DEFAULT_LOCALE, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits,
    maximumFractionDigits,
  }).format(value);
}

function toDate(value?: string | number | Date | null): Date | null {
  if (value === null || value === undefined) {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value?: string | number | Date | null, options?: Intl.DateTimeFormatOptions): string {
  const date = toDate(value);
  if (!date) {
    return FALLBACK;
  }
  return new Intl.DateTimeFormat(DEFAULT_LOCALE, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: DEFAULT_TIME_ZONE,
    ...options,
  }).format(date);
}

export function formatDate(value?: string | number | Date | null, options?: Intl.DateTimeFormatOptions): string {
  const date = toDate(value);
  if (!date) {
    return FALLBACK;
  }
  return new Intl.DateTimeFormat(DEFAULT_LOCALE, {
    dateStyle: "medium",
    timeZone: DEFAULT_TIME_ZONE,
    ...options,
  }).format(date);
}
