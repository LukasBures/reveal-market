import { NextResponse } from "next/server";
import { logger } from "@/lib/logging";
import { isValidEmail } from "@/lib/validation";
import crypto from "node:crypto";

const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_LIMIT = 6;
const rateBucket = new Map<string, { count: number; resetAt: number }>();

const hashValue = (value: string) =>
  crypto.createHash("sha256").update(value).digest("hex").slice(0, 12);

const getClientKey = (request: Request) => {
  const forwardedFor = request.headers.get("x-forwarded-for") ?? "";
  const candidate = forwardedFor.split(",")[0]?.trim();
  return candidate || request.headers.get("x-real-ip") || "unknown";
};

const rateLimit = (key: string) => {
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

const MAX_DISCORD_CONTENT_LENGTH = 2000;
const MAX_MESSAGE_LENGTH = 1800;
const MAX_NAME_LENGTH = 100;
const MAX_EMAIL_LENGTH = 100;

const normalizeInput = (value: unknown) => (typeof value === "string" ? value.trim() : "");

const truncate = (value: string, max: number) =>
  value.length > max ? `${value.slice(0, max - 1)}…` : value;

async function sendDiscord(webhookUrl: string, body: { name: string; email?: string; message: string }) {
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
    throw new Error(
      `Discord webhook failed with status ${response.status}${bodyText ? `: ${bodyText}` : ""}`,
    );
  }
}

export async function POST(request: Request) {
  try {
    const clientKey = getClientKey(request);
    if (rateLimit(clientKey)) {
      return NextResponse.json({ ok: false, error: "rate_limited" }, { status: 429 });
    }
    const { name, email, message, turnstileToken } = await request.json();
    const safeName = normalizeInput(name);
    const safeEmail = normalizeInput(email);
    const safeMessage = normalizeInput(message);
    const safeTurnstileToken = normalizeInput(turnstileToken);

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

    const turnstileSecret = process.env.CONTACT_TURNSTILE_SECRET;
    const envLabel = (process.env.RM_ENVIRONMENT ?? process.env.NODE_ENV ?? "").toLowerCase();
    const allowTurnstileBypass =
      envLabel === "local" || envLabel === "development" || envLabel === "dev" || envLabel === "test";
    if (turnstileSecret && !allowTurnstileBypass) {
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
    } else if (turnstileSecret) {
      logger.warn("contact_form.turnstile_bypass", { environment: envLabel || "unknown" });
    } else {
      logger.warn("contact_form.email_disabled", { reason: "missing_turnstile_secret" });
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
    logger.error("contact_form.error", { error: (error as Error).message });
    return NextResponse.json({ ok: false }, { status: 500 });
  }
}
