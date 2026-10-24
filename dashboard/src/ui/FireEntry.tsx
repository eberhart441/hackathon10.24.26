// Fire-mode entry flash (Req 13.1–13.3): 1 s red full-screen flash, skipped under reduced motion.
import { useEffect, useState } from "preact/hooks";
import { COLORS } from "../scene/palette";

export function FireEntry() {
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [on, setOn] = useState(!reduce);
  useEffect(() => {
    if (!on) return;
    const t = setTimeout(() => setOn(false), 1000);
    return () => clearTimeout(t);
  }, []);
  if (!on) return null;
  return (
    <div aria-hidden="true" style={{ position: "fixed", inset: 0, background: COLORS.alarmRed, pointerEvents: "none", zIndex: 100, animation: "rs-fire-flash 1s ease-out forwards" }}>
      <style>{"@keyframes rs-fire-flash{from{opacity:.85}to{opacity:0}}"}</style>
    </div>
  );
}
