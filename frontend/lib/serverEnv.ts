import { logger } from "./logging";

export type ServerEnv = {
  apiBaseUrl: string;
};

function resolveApiBase(): string {
  const preferDockerApi = process.env.RUNNING_IN_DOCKER === "true";
  const fallbackBase = process.env.RM_OFFLINE_API_BASE_URL ?? "https://api.revealmarket.xyz";
  const explicitBase = process.env.RM_API_BASE_URL ?? null;
  const publicBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? null;
  const selectedBase =
    (preferDockerApi && explicitBase ? explicitBase : null) ?? explicitBase ?? publicBase ?? fallbackBase;

  if (!explicitBase && !publicBase) {
    logger.warn("serverEnv:missing_base_url", { fallback: fallbackBase });
  }

  return assertValidUrl(selectedBase, "API base URL");
}

function assertValidUrl(value: string, label: string): string {
  try {
    // new URL also normalizes protocol casing / strips invalid entries.
    return new URL(value).toString().replace(/\/$/, "");
  } catch {
    throw new Error(`${label} is invalid: ${value}`);
  }
}

export function getServerEnv(): ServerEnv {
  return Object.freeze({
    apiBaseUrl: resolveApiBase(),
  });
}

export const serverEnv = getServerEnv();
