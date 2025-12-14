import { logger } from "./logging";

export type ServerEnv = {
  apiBaseUrl: string;
  mode: "local" | "prod";
};

import { resolveUrlConfig } from "./env-presets";

export function getServerEnv(): ServerEnv {
  const urls = resolveUrlConfig();
  logger.info("serverEnv:resolved", {
    apiBaseUrl: urls.apiBaseInternal || urls.apiBaseUrl,
    mode: urls.mode,
  });
  return Object.freeze({
    apiBaseUrl: urls.apiBaseInternal || urls.apiBaseUrl,
    mode: urls.mode,
  });
}

export const serverEnv = getServerEnv();
