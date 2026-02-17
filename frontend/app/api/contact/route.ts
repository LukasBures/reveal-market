import { NextResponse } from "next/server";
import { logger } from "@/lib/logging";
import crypto from "node:crypto";

type EmailConfig = {
  host: string;
  port: number;
  user?: string;
  pass?: string;
  secure: boolean;
  from: string;
  to: string;
};

const EMAIL_TO = "hi@revealmarket.xyz";
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

function resolveEmailConfig(): EmailConfig | null {
  const host = process.env.CONTACT_SMTP_HOST;
  const port = Number(process.env.CONTACT_SMTP_PORT ?? 0);
  const user = process.env.CONTACT_SMTP_USER;
  const pass = process.env.CONTACT_SMTP_PASS;
  const from = process.env.CONTACT_FROM ?? "no-reply@revealmarket.xyz";
  const secure = process.env.CONTACT_SMTP_SECURE === "true";

  if (!host || !port) {
    return null;
  }

  return { host, port, user, pass, secure, from, to: EMAIL_TO };
}

async function sendEmail(config: EmailConfig, body: { name: string; email: string; message: string }) {
  const nodemailer = await import("nodemailer");
  const transport = nodemailer.createTransport({
    host: config.host,
    port: config.port,
    secure: config.secure,
    auth: config.user && config.pass ? { user: config.user, pass: config.pass } : undefined,
  });

  const subject = `[Contact] ${body.name} via revealmarket.xyz`;
  const text = [
    `Name: ${body.name}`,
    `Email: ${body.email}`,
    "",
    "Message:",
    body.message,
  ].join("\n");

  await transport.sendMail({
    from: config.from,
    to: config.to,
    replyTo: body.email,
    subject,
    text,
  });
}

export async function POST(request: Request) {
  try {
    const clientKey = getClientKey(request);
    if (rateLimit(clientKey)) {
      return NextResponse.json({ ok: false, error: "rate_limited" }, { status: 429 });
    }
    const { name, email, message, turnstileToken } = await request.json();
    const safeName = typeof name === "string" ? name.trim() : "";
    const safeEmail = typeof email === "string" ? email.trim() : "";
    const safeMessage = typeof message === "string" ? message.trim() : "";
    const safeTurnstileToken = typeof turnstileToken === "string" ? turnstileToken.trim() : "";

    const emailRegex = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    if (!safeName || !safeEmail || !safeMessage || !emailRegex.test(safeEmail)) {
      return NextResponse.json(
        { ok: false, error: "missing_fields" },
        { status: 400 }
      );
    }

    const turnstileSecret = process.env.CONTACT_TURNSTILE_SECRET;
    if (turnstileSecret) {
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
      logger.warn("contact_form.email_disabled", { reason: "missing_turnstile_secret" });
    }

    logger.info("contact_form.submission", {
      name_length: safeName.length,
      email_hash: hashValue(safeEmail.toLowerCase()),
      message_length: safeMessage.length,
    });

    const emailConfig = resolveEmailConfig();
    if (!emailConfig) {
      logger.warn("contact_form.email_disabled", { reason: "missing_smtp_config" });
      return NextResponse.json({ ok: true, forwarded: false }, { status: 202 });
    }

    await sendEmail(emailConfig, { name: safeName, email: safeEmail, message: safeMessage });
    return NextResponse.json({ ok: true, forwarded: true }, { status: 202 });
  } catch (error) {
    logger.error("contact_form.error", { error: (error as Error).message });
    return NextResponse.json({ ok: false }, { status: 500 });
  }
}
