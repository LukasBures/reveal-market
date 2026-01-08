"use server";

import { cookies } from "next/headers";
import {
  LANDING_ACCESS_COOKIE_MAX_AGE_SECONDS,
  LANDING_ACCESS_COOKIE_NAME,
} from "@/lib/access-gate";
import { resolveUrlConfig } from "@/lib/env-presets";

type LandingAccessFormState = {
  error?: string;
  success?: boolean;
};

const resolveAccessCode = () => process.env.LANDING_ACCESS_CODE?.trim() ?? "";

const resolveSiteUrl = () => {
  const config = resolveUrlConfig();
  return config.siteUrl;
};

const isProdLike = () => resolveUrlConfig().mode === "prod";

const shouldUseSecureCookie = (): boolean => {
  const siteUrl = resolveSiteUrl();
  try {
    const parsed = new URL(siteUrl.startsWith("http") ? siteUrl : `https://${siteUrl}`);
    if (parsed.protocol === "https:") return true;
  } catch {
    // fall through to environment-based fallback
  }
  return isProdLike();
};

export async function requestLandingAccessAction(
  _prevState: LandingAccessFormState,
  formData: FormData,
): Promise<LandingAccessFormState> {
  const configuredCode = resolveAccessCode();

  if (!configuredCode) {
    return { error: "Access code is not configured." };
  }

  const rawCode = formData.get("accessCode");
  const candidate = typeof rawCode === "string" ? rawCode.trim() : "";

  if (!candidate) {
    return { error: "Enter the login code." };
  }

  if (candidate !== configuredCode) {
    return { error: "Invalid login code." };
  }

  const cookieStore = await cookies();
  cookieStore.set({
    name: LANDING_ACCESS_COOKIE_NAME,
    value: "granted",
    httpOnly: true,
    secure: shouldUseSecureCookie(),
    sameSite: "lax",
    path: "/",
    maxAge: LANDING_ACCESS_COOKIE_MAX_AGE_SECONDS,
  });

  return { success: true };
}

export type { LandingAccessFormState };
