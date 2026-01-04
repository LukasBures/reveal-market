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

export function formatUsdCompact(
  value?: number | null,
  options?: Pick<Intl.NumberFormatOptions, "minimumFractionDigits" | "maximumFractionDigits">,
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return FALLBACK;
  }
  return new Intl.NumberFormat(DEFAULT_LOCALE, {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: options?.maximumFractionDigits ?? 1,
    minimumFractionDigits: options?.minimumFractionDigits ?? 0,
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
  const datePart = formatDate(date, { dateStyle: options?.dateStyle ?? "medium", timeZone: DEFAULT_TIME_ZONE });
  const timePart = formatTime(date, {
    hour: options?.hour ?? "numeric",
    minute: options?.minute ?? "2-digit",
    second: options?.second,
    hour12: options?.hour12 ?? false,
    timeZone: options?.timeZone ?? DEFAULT_TIME_ZONE,
  });
  return `${datePart} ${timePart}`;
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

export function formatTime(value?: string | number | Date | null, options?: Intl.DateTimeFormatOptions): string {
  const date = toDate(value);
  if (!date) {
    return FALLBACK;
  }
  const formatterOptions: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: DEFAULT_TIME_ZONE,
    ...options,
  };
  delete (formatterOptions as any).timeStyle;
  return new Intl.DateTimeFormat(DEFAULT_LOCALE, formatterOptions).format(date);
}

export function normalizeHex(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const hasPrefix = trimmed.startsWith("0x") || trimmed.startsWith("0X");
  const raw = hasPrefix ? trimmed.slice(2) : trimmed;
  if (!raw) return null;
  const lower = raw.toLowerCase();
  if (!/^[0-9a-f]+$/.test(lower)) return null;
  if (!hasPrefix && !(lower.length === 40 || lower.length === 64 || /[a-f]/.test(lower))) {
    return null;
  }
  return `0x${raw}`;
}

export function normalizeTxHash(value?: string | null): string | null {
  const normalized = normalizeHex(value);
  if (!normalized) return null;
  return normalized.length === 66 ? normalized : null;
}
