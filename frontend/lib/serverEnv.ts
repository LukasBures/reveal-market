import "server-only";

import { logger } from "./logging";

export type ServerEnv = {
  apiBaseUrl: string;
};

const preferDockerApi = process.env.RUNNING_IN_DOCKER === "true";
const offlineFallback = process.env.RM_OFFLINE_API_BASE_URL ?? "http://localhost:8000";

const selectedBase =
  (preferDockerApi ? process.env.RM_API_BASE_URL : undefined) ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.RM_API_BASE_URL ??
  null;

function resolveApiBase(): string {
  if (selectedBase) {
    return assertValidUrl(selectedBase, "API base URL");
  }
  if (process.env.NODE_ENV !== "production") {
    logger.info("serverEnv:offline_fallback", { fallback: offlineFallback });
    return assertValidUrl(offlineFallback, "offline API base URL");
  }
  throw new Error(
    "Missing RM_API_BASE_URL or NEXT_PUBLIC_API_BASE_URL. Set one of them so server components can reach the API.",
  );
}

function assertValidUrl(value: string, label: string): string {
  try {
    // new URL also normalizes protocol casing / strips invalid entries.
    return new URL(value).toString().replace(/\/$/, "");
  } catch {
    throw new Error(`${label} is invalid: ${value}`);
  }
}

export const serverEnv: ServerEnv = Object.freeze({
  apiBaseUrl: resolveApiBase(),
});

export function getServerEnv(): ServerEnv {
  return serverEnv;
}
