import crypto from "crypto";

/** Generate a license key like CLP-A3BK9-XW4M2-7YNHP */
export function generateLicenseKey(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // no 0/O/1/I
  const segments: string[] = [];
  for (let s = 0; s < 3; s++) {
    let seg = "";
    for (let i = 0; i < 5; i++) {
      seg += chars[crypto.randomInt(chars.length)];
    }
    segments.push(seg);
  }
  return `CLP-${segments.join("-")}`;
}

export const PLAN_LIMITS: Record<
  string,
  { answers: number; screenshots: number; duration_days: number | null }
> = {
  free: { answers: 10, screenshots: 5, duration_days: null },
  pro: { answers: Infinity, screenshots: Infinity, duration_days: 30 },
  promax: { answers: Infinity, screenshots: Infinity, duration_days: 365 },
};

/** Razorpay amounts in paise */
export const PLAN_PRICES: Record<string, number> = {
  pro: 49900, // ₹499
  promax: 299900, // ₹2999
};
