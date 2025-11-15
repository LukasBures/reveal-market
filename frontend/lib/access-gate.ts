export const LANDING_ACCESS_COOKIE_NAME = "rm_landing_access";
export const LANDING_ACCESS_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30; // 30 days

export function isLandingGateEnabled(): boolean {
  return Boolean(process.env.LANDING_ACCESS_CODE);
}
