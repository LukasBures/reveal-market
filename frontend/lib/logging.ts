type LogLevel = "debug" | "info" | "warn" | "error";

const ORDER: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
};

const defaultLevel: LogLevel = "info";
const parseLogLevel = (value: string | undefined | null): LogLevel | null => {
  if (!value) {
    return null;
  }
  const normalized = value.toLowerCase() as LogLevel;
  return normalized in ORDER ? normalized : null;
};

const envLevelRaw = process.env.NEXT_PUBLIC_LOG_LEVEL || process.env.LOG_LEVEL;
const envLevel = parseLogLevel(envLevelRaw) ?? defaultLevel;

const activeLevel: LogLevel = envLevel;
const browserLoggingEnabled = process.env.NEXT_PUBLIC_ENABLE_BROWSER_LOGS === "true";
const isBrowser = typeof window !== "undefined";

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

const LOGGER_NAME = "frontend";

const formatTimestamp = () => (typeof Date !== "undefined" ? new Date().toISOString() : "0000-00-00T00:00:00.000Z");

const extractCaller = () => {
  if (typeof Error === "undefined") {
    return "-";
  }
  const err = new Error();
  if (!err.stack) {
    return "-";
  }
  const frames = err.stack.split("\n").map((line) => line.trim());
  for (let i = 2; i < frames.length; i += 1) {
    const match = frames[i].match(/\(?(.+?):(\d+):\d+\)?$/);
    if (match) {
      const [, filePath, line] = match;
      const segments = filePath.split(/[/\\]/);
      const file = segments[segments.length - 1] || filePath;
      return `${file}:${line}`;
    }
  }
  return "-";
};

const formatLine = (level: LogLevel, message: string, meta?: Record<string, unknown>) => {
  const payload: Record<string, unknown> = {
    timestamp: formatTimestamp(),
    level: level.toUpperCase(),
    logger: LOGGER_NAME,
    location: extractCaller(),
    event: message,
    message,
    service: LOGGER_NAME,
    request_id: meta?.request_id ?? "-",
  };
  if (meta) {
    Object.entries(meta).forEach(([key, value]) => {
      payload[key] = value;
    });
  }
  return JSON.stringify(payload);
};

const baseLogger = {
  debug(message: string, meta?: Record<string, unknown>) {
    if (ORDER[activeLevel] <= ORDER.debug && (!isBrowser || browserLoggingEnabled)) {
      console.debug(formatLine("debug", message, meta));
    }
  },
  info(message: string, meta?: Record<string, unknown>) {
    if (ORDER[activeLevel] <= ORDER.info && (!isBrowser || browserLoggingEnabled)) {
      console.info(formatLine("info", message, meta));
    }
  },
  warn(message: string, meta?: Record<string, unknown>) {
    if (!isBrowser || browserLoggingEnabled) {
      console.warn(formatLine("warn", message, meta));
    }
  },
  error(message: string, meta?: Record<string, unknown>) {
    if (!isBrowser || browserLoggingEnabled) {
      console.error(formatLine("error", message, meta));
    }
  },
  clientWarn(message: string, meta?: Record<string, unknown>) {
    if (isBrowser) {
      console.warn(formatLine("warn", message, meta));
      const source = process.env.NEXT_PUBLIC_FRONTEND_LOG_ENDPOINT;
      if (source) {
        fetch(source, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ level: "warn", message, meta }),
          keepalive: true,
        }).catch(() => {});
      }
    } else {
      baseLogger.warn(message, meta);
    }
  },
  clientError(message: string, meta?: Record<string, unknown>) {
    if (isBrowser) {
      console.error(formatLine("error", message, meta));
      const source = process.env.NEXT_PUBLIC_FRONTEND_LOG_ENDPOINT;
      if (source) {
        fetch(source, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ level: "error", message, meta }),
          keepalive: true,
        }).catch(() => {});
      }
    } else {
      baseLogger.error(message, meta);
    }
  },
};

if (!isBrowser) {
  baseLogger.info("logging initialized", {
    event: "logging.init",
    log_level: activeLevel.toUpperCase(),
    level_source: envLevelRaw ?? defaultLevel,
    browser_logging_enabled: browserLoggingEnabled,
  });
}

let heartbeatStarted = false;

export function ensureHeartbeat(intervalMs = HEARTBEAT_INTERVAL_MS) {
  if (heartbeatStarted || typeof globalThis === "undefined" || isBrowser) {
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
