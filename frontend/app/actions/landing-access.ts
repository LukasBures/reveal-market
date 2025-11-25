"use server";

import { cookies } from "next/headers";
import {
  LANDING_ACCESS_COOKIE_MAX_AGE_SECONDS,
  LANDING_ACCESS_COOKIE_NAME,
} from "@/lib/access-gate";

type LandingAccessFormState = {
  error?: string;
  success?: boolean;
};

const resolveAccessCode = () => process.env.LANDING_ACCESS_CODE?.trim() ?? "";

const resolveSiteUrl = () =>
  process.env.NEXT_PUBLIC_SITE_URL ??
  process.env.RM_SITE_URL ??
  process.env.VERCEL_URL ??
  "https://revealmarket.xyz";

const shouldUseSecureCookie = (): boolean => {
  const siteUrl = resolveSiteUrl();
  try {
    const parsed = new URL(siteUrl.startsWith("http") ? siteUrl : `https://${siteUrl}`);
    return parsed.protocol === "https:";
  } catch {
    return process.env.NODE_ENV === "production";
  }
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
