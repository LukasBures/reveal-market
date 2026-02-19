"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type SubmissionState = "idle" | "submitting" | "success" | "error";

type ContactFormProps = {
  siteKey?: string;
};

type Turnstile = {
  render: (element: HTMLElement, options: Record<string, unknown>) => string;
  reset: (widgetId?: string) => void;
};

export function ContactForm({ siteKey }: ContactFormProps) {
  const [status, setStatus] = useState<SubmissionState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [captchaError, setCaptchaError] = useState<string | null>(null);
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const widgetRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const isValidEmail = (value: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value.trim());

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

    const renderTurnstile = () => {
      const turnstile = (window as unknown as { turnstile?: Turnstile }).turnstile;
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

    const turnstileGlobal = (window as unknown as { turnstile?: Turnstile }).turnstile;
    if (turnstileGlobal) {
      renderTurnstile();
      return;
    }

    const existingScript = document.getElementById("cf-turnstile");
    if (existingScript) {
      if ((window as unknown as { turnstile?: Turnstile }).turnstile) {
        renderTurnstile();
      } else {
        existingScript.addEventListener("load", renderTurnstile);
        return () => existingScript.removeEventListener("load", renderTurnstile);
      }
      return;
    }

    const script = document.createElement("script");
    script.id = "cf-turnstile";
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.onload = renderTurnstile;
    document.head.appendChild(script);

    return () => {
      script.onload = null;
    };
  }, [siteKey]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("submitting");
    setError(null);

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

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...payload, turnstileToken }),
      });
      if (!response.ok) {
        setError("We couldn't submit that. Please try again in a moment.");
        setStatus("error");
        return;
      }
      setStatus("success");
      event.currentTarget.reset();
      setTurnstileToken(null);
      const turnstile = (window as unknown as { turnstile?: Turnstile }).turnstile;
      if (turnstile && widgetRef.current) {
        turnstile.reset(widgetRef.current);
      }
    } catch (err) {
      setError("We couldn't submit that. Please try again in a moment.");
      setStatus("error");
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-col space-y-5 rounded-2xl border border-white/10 bg-white/5 p-7 text-base sm:p-8 flex-1"
    >
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2 text-sm text-slate-200">
          <span className="text-white">Name</span>
          <input
            name="name"
            className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-white outline-none ring-brand-400/60 focus:ring"
            placeholder="Your name (optional)"
          />
        </label>
        <label className="space-y-2 text-sm text-slate-200">
          <span className="text-white">Email</span>
          <input
            type="email"
            name="email"
            className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-3 text-white outline-none ring-brand-400/60 focus:ring"
            placeholder="you@example.com (optional)"
          />
        </label>
      </div>
      <label className="space-y-2 text-sm text-slate-200">
        <span className="text-white">How can we help?</span>
        <textarea
          name="message"
          required
          rows={5}
          className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-3 text-white outline-none ring-brand-400/60 focus:ring"
          placeholder="Share context about your use case, diligence, or integration needs."
        />
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
        disabled={status === "submitting"}
        className="w-full rounded-full bg-brand-500 px-5 py-4 text-center text-sm font-semibold uppercase tracking-[0.25em] text-white transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {status === "submitting" ? "Sending..." : "Send message"}
      </button>
    </form>
  );
}
