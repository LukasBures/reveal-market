type LogLevel = "debug" | "info" | "warn" | "error";

const ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

const envLevel =
  (process.env.NEXT_PUBLIC_LOG_LEVEL as LogLevel | undefined) ||
  (process.env.LOG_LEVEL as LogLevel | undefined) ||
  "info";

const activeLevel: LogLevel = ORDER[envLevel] ? envLevel : "info";

const DEFAULT_HEARTBEAT_INTERVAL_MS = 60 * 1000;

const resolveHeartbeatInterval = () => {
  const raw =
    process.env.NEXT_PUBLIC_HEARTBEAT_INTERVAL_MS ?? process.env.HEARTBEAT_INTERVAL_MS;
  const parsed = raw ? Number(raw) : NaN;
  if (Number.isFinite(parsed) && parsed > 0) {
    return parsed;
  }
  return DEFAULT_HEARTBEAT_INTERVAL_MS;
};

const HEARTBEAT_INTERVAL_MS = resolveHeartbeatInterval();

const formatLine = (level: LogLevel, message: string, meta?: Record<string, unknown>) => {
  const timestamp =
    typeof Date !== "undefined" ? new Date().toISOString() : "0000-00-00T00:00:00.000Z";
  const payload =
    meta && Object.keys(meta).length > 0 ? JSON.stringify(meta) : "{}";
  return `${timestamp} | ${level.toUpperCase()} | frontend | ${message} | ${payload}`;
};

const baseLogger = {
  debug(message: string, meta?: Record<string, unknown>) {
    if (ORDER[activeLevel] <= ORDER.debug) {
      console.debug(formatLine("debug", message, meta));
    }
  },
  info(message: string, meta?: Record<string, unknown>) {
    if (ORDER[activeLevel] <= ORDER.info) {
      console.info(formatLine("info", message, meta));
    }
  },
  warn(message: string, meta?: Record<string, unknown>) {
    console.warn(formatLine("warn", message, meta));
  },
  error(message: string, meta?: Record<string, unknown>) {
    console.error(formatLine("error", message, meta));
  },
};

let heartbeatStarted = false;

export function ensureHeartbeat(intervalMs = HEARTBEAT_INTERVAL_MS) {
  if (heartbeatStarted || typeof globalThis === "undefined") {
    return;
  }
  heartbeatStarted = true;
  const getUptime = () => {
    if (typeof process !== "undefined" && typeof process.uptime === "function") {
      return Math.round(process.uptime());
    }
    return undefined;
  };

  setInterval(() => {
    baseLogger.info("heartbeat", {
      heartbeatIntervalMs: intervalMs,
      uptimeSeconds: getUptime(),
    });
  }, intervalMs).unref?.();
}

export const logger = baseLogger;
