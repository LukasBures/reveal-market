import { logger } from "./logging";

export type ServerEnv = {
  apiBaseUrl: string;
};

import { resolveUrlConfig } from "./env-presets";

export function getServerEnv(): ServerEnv {
  const urls = resolveUrlConfig();
  logger.info("serverEnv:resolved", { apiBaseUrl: urls.apiBaseInternal || urls.apiBaseUrl });
  return Object.freeze({
    apiBaseUrl: urls.apiBaseInternal || urls.apiBaseUrl,
  });
}

export const serverEnv = getServerEnv();
