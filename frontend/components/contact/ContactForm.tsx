"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { isValidEmail } from "@/lib/validation";

type SubmissionState = "idle" | "submitting" | "success" | "error";

type ContactFormProps = {
  siteKey?: string;
};

const MAX_MESSAGE_LENGTH = 1800;
const MAX_NAME_LENGTH = 100;
const MAX_EMAIL_LENGTH = 100;

type Turnstile = {
  render: (element: HTMLElement, options: Record<string, unknown>) => string;
  reset: (widgetId?: string) => void;
};

export function ContactForm({ siteKey }: ContactFormProps) {
  const [status, setStatus] = useState<SubmissionState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [captchaError, setCaptchaError] = useState<string | null>(null);
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [messageLength, setMessageLength] = useState(0);
  const widgetRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!siteKey || !containerRef.current) {
      return;
    }

    const isLocalhost = (() => {
      if (typeof window === "undefined") return false;
      const host = window.location?.hostname ?? "";
      return host === "localhost" || host === "127.0.0.1";
    })();
    const isTestEnv =
      process.env.NODE_ENV === "test" ||
      process.env.VITEST === "true" ||
      process.env.VITEST === "1" ||
      Boolean(process.env.VITEST_WORKER_ID);
    if (isLocalhost && !isTestEnv) {
      return;
    }

    const getTurnstile = (): Turnstile | undefined =>
      (window as unknown as { turnstile?: Turnstile }).turnstile;
    const renderTurnstile = () => {
      const turnstile = getTurnstile();
      if (!turnstile || !containerRef.current) return;
      containerRef.current.innerHTML = "";
      widgetRef.current = turnstile.render(containerRef.current, {
        sitekey: siteKey,
        size: "flexible",
        callback: (token: string) => {
          setTurnstileToken(token);
          setCaptchaError(null);
        },
        "error-callback": () => {
          setCaptchaError("Verification failed. Please retry.");
          setTurnstileToken(null);
        },
        "timeout-callback": () => {
          setCaptchaError("Verification timed out. Please retry.");
          setTurnstileToken(null);
        },
        "expired-callback": () => setTurnstileToken(null),
      });
    };

    let cleanup: (() => void) | undefined;
    const turnstileGlobal = getTurnstile();
    if (turnstileGlobal) {
      renderTurnstile();
    } else {
      const existingScript = document.getElementById("cf-turnstile");
      if (existingScript) {
        if (getTurnstile()) {
          renderTurnstile();
        } else {
          existingScript.addEventListener("load", renderTurnstile);
          cleanup = () => existingScript.removeEventListener("load", renderTurnstile);
        }
      } else {
        const script = document.createElement("script");
        script.id = "cf-turnstile";
        script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        script.async = true;
        script.defer = true;
        script.onload = renderTurnstile;
        document.head.appendChild(script);
        cleanup = () => {
          script.onload = null;
        };
      }
    }

    return () => {
      cleanup?.();
    };
  }, [siteKey]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("submitting");
    setError(null);
    setCaptchaError(null);

    const formData = new FormData(event.currentTarget);
    const payload = {
      name: String(formData.get("name") ?? "").trim(),
      email: String(formData.get("email") ?? "").trim(),
      message: String(formData.get("message") ?? "").trim(),
    };

    if (!payload.message) {
      setError("Please include a short note so we can understand your request.");
      setStatus("idle");
      return;
    }

    if (payload.name.length > MAX_NAME_LENGTH) {
      setError(`Please keep your name under ${MAX_NAME_LENGTH} characters.`);
      setStatus("idle");
      return;
    }

    if (payload.email.length > MAX_EMAIL_LENGTH) {
      setError(`Please keep your email under ${MAX_EMAIL_LENGTH} characters.`);
      setStatus("idle");
      return;
    }

    if (payload.message.length > MAX_MESSAGE_LENGTH) {
      setError(`Please keep your message under ${MAX_MESSAGE_LENGTH} characters.`);
      setStatus("idle");
      return;
    }

    if (payload.email && !isValidEmail(payload.email)) {
      setError("Please enter a valid email address or leave it blank.");
      setStatus("idle");
      return;
    }

    if (siteKey && !turnstileToken) {
      setError("Please complete the verification step.");
      setStatus("idle");
      return;
    }

    let response: Response;
    try {
      response = await fetch("/api/contact", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...payload, turnstileToken }),
      });
    } catch (err) {
      setError("We couldn't submit that. Please try again in a moment.");
      setStatus("error");
      return;
    }

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const errorCode = data?.error;
      if (errorCode === "missing_verification") {
        setError("Please complete the verification step.");
      } else if (errorCode === "verification_failed") {
        setError("Verification failed. Please retry.");
      } else if (errorCode === "rate_limited") {
        setError("Too many requests. Please try again in a few minutes.");
      } else if (errorCode === "missing_fields") {
        setError("Please include a short note and a valid email address if provided.");
      } else if (errorCode === "name_too_long") {
        setError(`Please keep your name under ${MAX_NAME_LENGTH} characters.`);
      } else if (errorCode === "email_too_long") {
        setError(`Please keep your email under ${MAX_EMAIL_LENGTH} characters.`);
      } else if (errorCode === "message_too_long") {
        setError(`Please keep your message under ${MAX_MESSAGE_LENGTH} characters.`);
      } else {
        setError("We couldn't submit that. Please try again in a moment.");
      }
      setStatus("error");
      return;
    }

    setStatus("success");
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-1 min-h-0 flex-col space-y-5 rounded-2xl border border-white/10 bg-white/5 p-7 text-base sm:p-8"
    >
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2 text-sm text-slate-200">
          <span className="text-white">Name</span>
          <input
            name="name"
            maxLength={MAX_NAME_LENGTH}
            disabled={status === "submitting" || status === "success"}
            className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none ring-brand-400/60 focus:ring"
            placeholder="Your name (optional)"
          />
        </label>
        <label className="space-y-2 text-sm text-slate-200">
          <span className="text-white">Email</span>
          <input
            type="email"
            name="email"
            maxLength={MAX_EMAIL_LENGTH}
            disabled={status === "submitting" || status === "success"}
            className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none ring-brand-400/60 focus:ring"
            placeholder="you@example.com (optional)"
          />
        </label>
      </div>
      <label className="flex flex-1 flex-col gap-2 text-sm text-slate-200">
        <span className="text-white">How can we help?</span>
        <textarea
          name="message"
          required
          rows={7}
          maxLength={MAX_MESSAGE_LENGTH}
          disabled={status === "submitting" || status === "success"}
          className="w-full min-h-[160px] flex-1 rounded-xl border border-white/10 bg-black/40 px-3 py-3 text-white outline-none ring-brand-400/60 focus:ring sm:min-h-[200px]"
          placeholder="Share context about your use case, diligence, or integration needs."
          onChange={(event) => setMessageLength(event.currentTarget.value.length)}
        />
        {messageLength >= 1500 ? (
          <p className="text-xs text-slate-400">
            {MAX_MESSAGE_LENGTH - messageLength} characters remaining
          </p>
        ) : null}
      </label>
      {error ? <p className="text-sm text-red-400">{error}</p> : null}
      {captchaError ? <p className="text-sm text-red-400">{captchaError}</p> : null}
      {siteKey ? (
        <div className="rounded-xl border border-white/10 bg-black/30 p-3">
          <div ref={containerRef} className="flex justify-center" />
        </div>
      ) : (
        <p className="text-sm text-yellow-300">Verification is temporarily offline; submissions will still be received.</p>
      )}
      {status === "success" ? (
        <p className="text-sm text-accent-300">Thanks — we received your note and will follow up.</p>
      ) : null}
      <button
        type="submit"
        disabled={status === "submitting" || status === "success"}
        className="w-full rounded-full bg-brand-500 px-5 py-4 text-center text-sm font-semibold uppercase tracking-[0.25em] text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {status === "submitting" ? "Sending..." : status === "success" ? "Sent" : "Send message"}
      </button>
    </form>
  );
}
