// Best-effort Screen Wake Lock (req 13.4). Silently no-ops if unsupported or rejected.
type Sentinel = { release(): Promise<void> };
type WakeLockNav = { wakeLock?: { request(type: "screen"): Promise<Sentinel> } };

export function startWakeLock(): () => void {
  let sentinel: Sentinel | null = null;
  let stopped = false;
  const request = async () => {
    try {
      const s = await (navigator as unknown as WakeLockNav).wakeLock?.request("screen");
      if (!s) return;
      if (stopped) void s.release().catch(() => {});
      else sentinel = s;
    } catch {
      /* unsupported or rejected: ignore */
    }
  };
  const onVisible = () => {
    if (document.visibilityState === "visible") void request();
  };
  document.addEventListener("visibilitychange", onVisible);
  void request();
  return () => {
    stopped = true;
    document.removeEventListener("visibilitychange", onVisible);
    sentinel?.release().catch(() => {});
    sentinel = null;
  };
}
