// Age_Text formatting (Req 12.5): "m:ss" below one hour, "h:mm:ss" from one hour.
// Pure, DOM-free.

/**
 * Formats elapsed seconds as Age_Text.
 * 0 -> "0:00", 42 -> "0:42", 3725 -> "1:02:05".
 * Fractions are floored; negative and non-finite input is treated as 0.
 */
export function formatAge(seconds: number): string {
  const total = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  if (h === 0) return `${m}:${ss}`;
  return `${h}:${String(m).padStart(2, "0")}:${ss}`;
}

/**
 * Inverse of formatAge, for tests. Accepts "m:ss" (m < 60) or "h:mm:ss" (h ≥ 1).
 * Returns NaN for any text formatAge could not have produced.
 */
export function parseAge(text: string): number {
  const short = /^(\d+):([0-5]\d)$/.exec(text);
  if (short) {
    const m = Number(short[1]);
    const s = Number(short[2]);
    return m < 60 ? m * 60 + s : NaN;
  }
  const long = /^([1-9]\d*):([0-5]\d):([0-5]\d)$/.exec(text);
  if (long) {
    return Number(long[1]) * 3600 + Number(long[2]) * 60 + Number(long[3]);
  }
  return NaN;
}
