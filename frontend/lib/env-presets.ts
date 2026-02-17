import { logger } from "@/lib/logging";

type ModePreset = {
  apiBase: string;
  apiInternal?: string;
  siteUrl: string;
  streamerPublic: string;
  streamerInternal: string;
};

const PRESETS: Record<string, ModePreset> = {
  local: {
    apiBase: "http://localhost:8000",
    apiInternal: "http://api:8000",
    siteUrl: "http://localhost:3000",
    streamerPublic: "http://localhost:8100",
    streamerInternal: "http://streamer:8100",
  },
  prod: {
    apiBase: "https://api.revealmarket.xyz",
    apiInternal: "http://api:8000",
    siteUrl: "https://revealmarket.xyz",
    streamerPublic: "https://stream.revealmarket.xyz",
    streamerInternal: "http://streamer:8100",
  },
};

const resolveMode = () => {
  const modeEnv = (process.env.RM_ENVIRONMENT ?? process.env.NEXT_PUBLIC_RM_ENVIRONMENT ?? "").toLowerCase();
  if (modeEnv) {
    return modeEnv.includes("prod") ? "prod" : "local";
  }
  const nodeEnv = (process.env.NODE_ENV ?? "").toLowerCase();
  return nodeEnv === "production" ? "prod" : "local";
};

const assertValidUrl = (value: string, label: string): string => {
  try {
    return new URL(value).toString().replace(/\/$/, "");
  } catch {
    throw new Error(`${label} is invalid: ${value}`);
  }
};

const coalesceUrl = (candidate: string | undefined | null, fallback: string, label: string) => {
  const value = (candidate ?? "").trim();
  if (!value) return assertValidUrl(fallback, label);
  try {
    return assertValidUrl(value, label);
  } catch (err) {
    logger.error("env-presets:invalid_url", { label, value });
    throw err;
  }
};

export function resolveUrlConfig() {
  const mode = resolveMode();
  const preset = PRESETS[mode] ?? PRESETS.local;
  const runningInDocker = (process.env.RUNNING_IN_DOCKER ?? "").toLowerCase() === "true";
  const apiBaseOverride = (process.env.RM_API_BASE_URL ?? "").trim() ||
    (process.env.NEXT_PUBLIC_API_BASE_URL ?? "");

  const safeCoalesce = (candidate: string | undefined | null, fallback: string, label: string) => {
    try {
      return coalesceUrl(candidate, fallback, label);
    } catch {
      const nodeEnv = (process.env.NODE_ENV ?? "").toLowerCase();
      if (mode === "prod" || nodeEnv === "production") {
        throw new Error(`${label} is invalid: ${candidate ?? ""}`);
      }
      return assertValidUrl(fallback, label);
    }
  };

  const apiBaseUrl = safeCoalesce(apiBaseOverride, preset.apiBase, "API base URL");
  const apiBaseInternal = runningInDocker && preset.apiInternal ? preset.apiInternal : apiBaseUrl;
  const siteUrl = safeCoalesce(process.env.NEXT_PUBLIC_SITE_URL ?? process.env.RM_SITE_URL, preset.siteUrl, "Site URL");
  const streamerPublic = safeCoalesce(
    process.env.NEXT_PUBLIC_PRICE_STREAMER_URL ??
      (runningInDocker ? process.env.STREAMER_PUBLIC_BASE_URL : undefined),
    preset.streamerPublic,
    "Streamer URL",
  );
  const streamerInternal = safeCoalesce(
    process.env.STREAMER_INTERNAL_URL ?? (runningInDocker ? preset.streamerInternal : streamerPublic),
    runningInDocker ? preset.streamerInternal : streamerPublic,
    "Streamer internal URL",
  );

  return Object.freeze({
    mode,
    apiBaseUrl,
    apiBaseInternal,
    siteUrl,
    streamerPublic,
    streamerInternal,
  });
}
