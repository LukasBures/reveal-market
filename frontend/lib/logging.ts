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
  const timestamp = formatTimestamp();
  const location = extractCaller();
  const payload: Record<string, unknown> = meta ? { ...meta } : {};
  const rawRequestId = payload["requestId"];
  const requestId = typeof rawRequestId === "string" && rawRequestId ? rawRequestId : "-";
  if ("requestId" in payload) {
    delete payload["requestId"];
  }
  const serialized = Object.keys(payload).length > 0 ? JSON.stringify(payload) : "{}";
  return `${timestamp} | ${level.toUpperCase()} | ${LOGGER_NAME} | ${location} | ${message} | ${requestId} | ${serialized}`;
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
