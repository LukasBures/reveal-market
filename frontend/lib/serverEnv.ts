import { logger } from "./logging";

export type ServerEnv = {
  apiBaseUrl: string;
};

function resolveApiBase(): string {
  const preferDockerApi = process.env.RUNNING_IN_DOCKER === "true";
  const offlineFallback = process.env.RM_OFFLINE_API_BASE_URL ?? "http://localhost:8000";
  const forceOffline = process.env.RM_FORCE_OFFLINE === "true";
  const explicitBase = process.env.RM_API_BASE_URL ?? null;
  const selectedBase =
    (preferDockerApi && explicitBase ? explicitBase : null) ??
    explicitBase ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    null;

  if (selectedBase) {
    return assertValidUrl(selectedBase, "API base URL");
  }
  if (forceOffline || process.env.NODE_ENV !== "production") {
    logger.info("serverEnv:offline_fallback", { fallback: offlineFallback });
    return assertValidUrl(offlineFallback, "offline API base URL");
  }
  logger.warn("serverEnv:missing_base_url", { fallback: offlineFallback });
  return assertValidUrl(offlineFallback, "fallback API base URL");
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
