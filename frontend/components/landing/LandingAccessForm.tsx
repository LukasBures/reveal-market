"use client";

import { useActionState, useEffect, useState } from "react";
import { useFormStatus } from "react-dom";
import { useRouter } from "next/navigation";

import {
  requestLandingAccessAction,
  type LandingAccessFormState,
} from "@/app/actions/landing-access";

const INITIAL_STATE: LandingAccessFormState = {};

export function LandingAccessForm() {
  const [formVisible, setFormVisible] = useState(false);
  const [state, formAction] = useActionState(requestLandingAccessAction, INITIAL_STATE);
  const router = useRouter();

  useEffect(() => {
    if (state?.success) {
      router.refresh();
    }
  }, [state?.success, router]);

  return (
    <div className="flex w-full flex-col items-center gap-4 text-center">
      <button
        type="button"
        className="inline-flex items-center justify-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.35em] text-white transition hover:bg-white/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60"
        onClick={() => setFormVisible(true)}
        aria-expanded={formVisible}
      >
        Enter access code
      </button>
      {formVisible ? (
        <form
          action={formAction}
          className="flex w-full flex-col items-center gap-3 text-left sm:w-auto"
        >
          <input
            aria-label="Access code"
            type="password"
            name="accessCode"
            inputMode="text"
            autoComplete="off"
            className="w-full rounded-full border border-white/20 bg-black/40 px-4 py-2 text-center font-semibold tracking-[0.3em] text-white placeholder:text-slate-500"
            placeholder="••••••"
            required
          />
          {state?.error ? (
            <p className="text-sm text-rose-400" role="alert">
              {state.error}
            </p>
          ) : state?.success ? (
            <p className="text-sm text-emerald-300" role="status">
              Access granted. Loading the app…
            </p>
          ) : null}
          <SubmitButton />
        </form>
      ) : null}
    </div>
  );
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="inline-flex items-center justify-center gap-2 text-xs font-semibold uppercase tracking-[0.4em] text-white disabled:opacity-70"
    >
      {pending ? (
        <>
          <span className="h-3 w-3 animate-spin rounded-full border border-white/40 border-t-white" aria-hidden />
          Checking
        </>
      ) : (
        "Enter"
      )}
    </button>
  );
}
