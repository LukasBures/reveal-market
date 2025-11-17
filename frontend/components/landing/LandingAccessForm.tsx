"use client";

import { useEffect, useState } from "react";
import { useFormState, useFormStatus } from "react-dom";
import { useRouter } from "next/navigation";

import {
  requestLandingAccessAction,
  type LandingAccessFormState,
} from "@/app/actions/landing-access";

const INITIAL_STATE: LandingAccessFormState = {};

export function LandingAccessForm() {
  const [formVisible, setFormVisible] = useState(false);
  const [state, formAction] = useFormState(requestLandingAccessAction, INITIAL_STATE);
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
        className="text-xs font-semibold uppercase tracking-[0.5em] text-slate-400 transition hover:text-white"
        onClick={() => setFormVisible(true)}
        aria-expanded={formVisible}
      >
        Visit
      </button>
      {formVisible ? (
        <form
          action={formAction}
          className="flex w-full flex-col items-center gap-3 text-left sm:w-auto"
        >
          <label className="w-full text-xs uppercase tracking-[0.3em] text-slate-500">
            Login code
            <input
              type="password"
              name="accessCode"
              inputMode="text"
              autoComplete="off"
              className="mt-2 w-full rounded-full border border-white/20 bg-black/40 px-4 py-2 text-center font-semibold tracking-[0.3em] text-white placeholder:text-slate-500"
              placeholder="••••••"
              required
            />
          </label>
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
      className="text-xs font-semibold uppercase tracking-[0.4em] text-white"
    >
      {pending ? "Checking" : "Enter"}
    </button>
  );
}
