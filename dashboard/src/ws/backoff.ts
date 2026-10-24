// Reconnect backoff for the WS client (Req 7.4): 0.5 s doubling, capped at 5 s.

export const BACKOFF_BASE_MS = 500;
export const BACKOFF_CAP_MS = 5000;

/**
 * min(500 * 2^attempt, 5000) for attempt >= 0.
 * Negative or NaN attempts count as 0; fractional attempts are floored;
 * large (including Infinity) attempts return the cap without overflow.
 */
export function backoffMs(attempt: number): number {
  const a = Number.isNaN(attempt) ? 0 : Math.max(0, Math.floor(attempt));
  // 500 * 2^4 = 8000 already exceeds the cap; short-circuit to avoid huge powers.
  if (a >= 4) return BACKOFF_CAP_MS;
  return Math.min(BACKOFF_BASE_MS * 2 ** a, BACKOFF_CAP_MS);
}
