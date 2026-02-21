import crypto from "node:crypto";
import net from "node:net";

import { NextResponse } from "next/server";

import { logger } from "@/lib/logging";
import { getRedisClient } from "@/lib/redis";
import { isValidEmail } from "@/lib/validation";

const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_WINDOW_SECONDS = Math.ceil(RATE_WINDOW_MS / 1000);
const RATE_LIMIT = 6;
const MAX_CONTACT_BODY_BYTES = 8 * 1024;
const rateBucket = new Map<string, { count: number; resetAt: number }>();

const RATE_LIMIT_SCRIPT = `
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local count = redis.call("INCR", key)
if count == 1 then
  redis.call("EXPIRE", key, ttl)
else
  local current_ttl = redis.call("TTL", key)
  if current_ttl < 0 then
    redis.call("EXPIRE", key, ttl)
  end
end
return count
`;

const EDGE_CLIENT_IP_HEADERS = ["cf-connecting-ip", "x-vercel-ip", "true-client-ip", "fly-client-ip"] as const;

const hashValue = (value: string) => crypto.createHash("sha256").update(value).digest("hex").slice(0, 16);

const isEnvEnabled = (name: string): boolean => {
  const raw = process.env[name];
  if (!raw) {
    return false;
  }
  return ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
};

const parseTrustedProxyHops = (): number => {
  const raw = process.env.CONTACT_TRUSTED_PROXY_HOPS;
  if (!raw) {
    return 0;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }
  return parsed;
};

const normalizeIpCandidate = (value: string | null): string | null => {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  if (net.isIP(trimmed)) {
    return trimmed;
  }
  if (trimmed.startsWith("[") && trimmed.includes("]")) {
    const candidate = trimmed.slice(1, trimmed.indexOf("]"));
    if (net.isIP(candidate)) {
      return candidate;
    }
  }
  const lastColon = trimmed.lastIndexOf(":");
  if (lastColon > -1) {
    const maybeHost = trimmed.slice(0, lastColon);
    if (net.isIP(maybeHost)) {
      return maybeHost;
    }
  }
  return null;
};

const parseForwardedIps = (header: string): string[] =>
  header
    .split(",")
    .map((value) => normalizeIpCandidate(value))
    .filter((value): value is string => Boolean(value));

const getTrustedClientIp = (request: Request): string | null => {
  if (isEnvEnabled("CONTACT_TRUST_EDGE_IP_HEADERS")) {
    for (const headerName of EDGE_CLIENT_IP_HEADERS) {
      const value = normalizeIpCandidate(request.headers.get(headerName));
      if (value) {
        return value;
      }
    }
  }
  if (!isEnvEnabled("CONTACT_TRUST_PROXY_HEADERS")) {
    return null;
  }
  const trustedProxyHops = parseTrustedProxyHops();
  if (trustedProxyHops <= 0) {
    return null;
  }
  const forwardedFor = request.headers.get("x-forwarded-for") ?? "";
  const forwardedIps = parseForwardedIps(forwardedFor);
  if (forwardedIps.length > trustedProxyHops) {
    return forwardedIps[forwardedIps.length - 1 - trustedProxyHops];
  }
  const realIp = normalizeIpCandidate(request.headers.get("x-real-ip"));
  return realIp;
};

const getClientKey = (request: Request) => {
  const trustedIp = getTrustedClientIp(request);
  if (trustedIp) {
    return trustedIp;
  }
  return "unknown";
};

const rateLimitInMemory = (key: string) => {
  const now = Date.now();
  const existing = rateBucket.get(key);
  if (!existing || existing.resetAt <= now) {
    rateBucket.set(key, { count: 1, resetAt: now + RATE_WINDOW_MS });
    return false;
  }
  if (existing.count >= RATE_LIMIT) {
    return true;
  }
  existing.count += 1;
  return false;
};

const rateLimitRedis = async (key: string) => {
  const redis = getRedisClient();
  if (!redis) {
    return null;
  }
  const result = await redis.eval(RATE_LIMIT_SCRIPT, 1, key, RATE_WINDOW_SECONDS.toString());
  const count = Number(result);
  if (!Number.isFinite(count)) {
    throw new Error("rate_limit_eval_invalid");
  }
  return count > RATE_LIMIT;
};

const isAllowedDiscordHost = (hostname: string) =>
  hostname === "discord.com" ||
  hostname.endsWith(".discord.com") ||
  hostname === "discordapp.com" ||
  hostname.endsWith(".discordapp.com");

const MAX_DISCORD_CONTENT_LENGTH = 2000;
const MAX_MESSAGE_LENGTH = 1800;
const MAX_NAME_LENGTH = 100;
const MAX_EMAIL_LENGTH = 100;

class PayloadTooLargeError extends Error {}

class InvalidJsonError extends Error {}

const normalizeInput = (value: unknown) => (typeof value === "string" ? value.trim() : "");

const truncate = (value: string, max: number) => (value.length > max ? `${value.slice(0, max - 1)}…` : value);

const readJsonBodyWithLimit = async (request: Request, maxBytes: number): Promise<Record<string, unknown>> => {
  const contentLength = request.headers.get("content-length");
  if (contentLength) {
    const parsedLength = Number.parseInt(contentLength, 10);
    if (Number.isFinite(parsedLength) && parsedLength > maxBytes) {
      throw new PayloadTooLargeError("payload_too_large");
    }
  }
  const reader = request.body?.getReader();
  if (!reader) {
    throw new InvalidJsonError("invalid_json");
  }
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    if (!value) {
      continue;
    }
    totalBytes += value.byteLength;
    if (totalBytes > maxBytes) {
      throw new PayloadTooLargeError("payload_too_large");
    }
    chunks.push(value);
  }
  const body = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(body));
  } catch {
    throw new InvalidJsonError("invalid_json");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new InvalidJsonError("invalid_json");
  }
  return parsed as Record<string, unknown>;
};

async function sendDiscord(webhookUrl: string, body: { name: string; email?: string; message: string }) {
  const parsed = new URL(webhookUrl);
  if (parsed.protocol !== "https:" || !isAllowedDiscordHost(parsed.hostname)) {
    throw new Error("webhook_host_not_allowed");
  }
  const name = body.name ? body.name : "Anonymous";
  const contact = body.email ? body.email : "Not provided";
  const rawContent = [
    "**New contact submission**",
    `Name: ${name}`,
    `Contact: ${contact}`,
    "",
    truncate(body.message, MAX_MESSAGE_LENGTH),
  ].join("\n");
  const content = truncate(rawContent, MAX_DISCORD_CONTENT_LENGTH);

  const response = await fetch(webhookUrl, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "user-agent": "RevealMarket Contact/1.0",
    },
    body: JSON.stringify({
      content,
      username: "RevealMarket Contact",
      allowed_mentions: { parse: [] },
    }),
  });

  if (!response.ok) {
    const bodyText = await response.text().catch(() => "");
    throw new Error(`Discord webhook failed with status ${response.status}${bodyText ? `: ${bodyText}` : ""}`);
  }
}

export async function POST(request: Request) {
  try {
    const clientKey = getClientKey(request);
    const turnstileSecret = process.env.CONTACT_TURNSTILE_SECRET;
    const envLabel = (process.env.RM_ENVIRONMENT ?? process.env.NODE_ENV ?? "").toLowerCase();
    const isProdEnv = envLabel === "prod" || envLabel === "production";

    try {
      const redisLimited = await rateLimitRedis(`contact_rate:${clientKey}`);
      if (redisLimited === null) {
        if (isProdEnv) {
          logger.error("contact_form.rate_limit_unavailable", { reason: "missing_redis" });
          return NextResponse.json({ ok: false, error: "rate_limit_unavailable" }, { status: 503 });
        }
        if (rateLimitInMemory(clientKey)) {
          return NextResponse.json({ ok: false, error: "rate_limited" }, { status: 429 });
        }
      } else if (redisLimited) {
        return NextResponse.json({ ok: false, error: "rate_limited" }, { status: 429 });
      }
    } catch (error) {
      logger.warn("contact_form.rate_limit_failed", { error: (error as Error).message });
      if (rateLimitInMemory(clientKey)) {
        return NextResponse.json({ ok: false, error: "rate_limited" }, { status: 429 });
      }
    }

    const body = await readJsonBodyWithLimit(request, MAX_CONTACT_BODY_BYTES);
    const safeName = normalizeInput(body.name);
    const safeEmail = normalizeInput(body.email);
    const safeMessage = normalizeInput(body.message);
    const safeTurnstileToken = normalizeInput(body.turnstileToken);

    if (!safeMessage) {
      return NextResponse.json({ ok: false, error: "missing_fields" }, { status: 400 });
    }
    if (safeName.length > MAX_NAME_LENGTH) {
      return NextResponse.json({ ok: false, error: "name_too_long" }, { status: 400 });
    }
    if (safeEmail.length > MAX_EMAIL_LENGTH) {
      return NextResponse.json({ ok: false, error: "email_too_long" }, { status: 400 });
    }
    if (safeMessage.length > MAX_MESSAGE_LENGTH) {
      return NextResponse.json({ ok: false, error: "message_too_long" }, { status: 400 });
    }
    if (safeEmail && !isValidEmail(safeEmail)) {
      return NextResponse.json({ ok: false, error: "missing_fields" }, { status: 400 });
    }

    const allowTurnstileBypass =
      envLabel === "local" || envLabel === "development" || envLabel === "dev" || envLabel === "test";
    if (!turnstileSecret) {
      if (!allowTurnstileBypass) {
        logger.error("contact_form.turnstile_unavailable", { environment: envLabel || "unknown" });
        return NextResponse.json({ ok: false, error: "verification_unavailable" }, { status: 503 });
      }
      logger.warn("contact_form.turnstile_bypass", { environment: envLabel || "unknown" });
    } else if (turnstileSecret && !allowTurnstileBypass) {
      if (!safeTurnstileToken) {
        return NextResponse.json({ ok: false, error: "missing_verification" }, { status: 400 });
      }
      const formData = new URLSearchParams();
      formData.set("secret", turnstileSecret);
      formData.set("response", safeTurnstileToken);
      const verification = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
        method: "POST",
        body: formData,
        headers: {
          "content-type": "application/x-www-form-urlencoded",
        },
      });
      const result = (await verification.json()) as { success?: boolean; "error-codes"?: string[] };
      if (!result.success) {
        logger.warn("contact_form.verification_failed", { error_codes: result["error-codes"] });
        return NextResponse.json({ ok: false, error: "verification_failed" }, { status: 400 });
      }
    } else {
      logger.warn("contact_form.turnstile_bypass", { environment: envLabel || "unknown" });
    }

    logger.info("contact_form.submission", {
      name_length: safeName.length,
      email_hash: safeEmail ? hashValue(safeEmail.toLowerCase()) : undefined,
      message_length: safeMessage.length,
    });

    const discordWebhook = process.env.CONTACT_DISCORD_WEBHOOK_URL;
    if (discordWebhook) {
      await sendDiscord(discordWebhook, { name: safeName, email: safeEmail, message: safeMessage });
      return NextResponse.json({ ok: true, forwarded: true, channel: "discord" }, { status: 202 });
    }
    logger.warn("contact_form.discord_disabled", { reason: "missing_discord_webhook" });
    return NextResponse.json({ ok: true, forwarded: false }, { status: 202 });
  } catch (error) {
    if (error instanceof PayloadTooLargeError) {
      return NextResponse.json({ ok: false, error: "payload_too_large" }, { status: 413 });
    }
    if (error instanceof InvalidJsonError) {
      return NextResponse.json({ ok: false, error: "invalid_json" }, { status: 400 });
    }
    logger.error("contact_form.error", { error: (error as Error).message });
    return NextResponse.json({ ok: false }, { status: 500 });
  }
}
