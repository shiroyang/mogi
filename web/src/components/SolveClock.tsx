// The clock on the problem page: time spent on this problem, in this browser.
// It counts while the tab is in front and you did something in the last five minutes.
// The count lives in localStorage, so a reload or a second tab carries on from it.
import { useEffect, useState } from "react";
import { clockText } from "../model";

const IDLE_MS = 5 * 60 * 1000;
const EVENTS = ["keydown", "pointerdown", "pointermove", "scroll"] as const;
const storageKey = (pid: string) => `mogi-time-${pid}`;

export function readSolveSeconds(pid: string): number {
  try { return Math.max(0, parseInt(localStorage.getItem(storageKey(pid)) || "0", 10) || 0); } catch { return 0; }
}
export function resetSolveSeconds(pid: string): void {
  try { localStorage.removeItem(storageKey(pid)); } catch { /* ignore */ }
}

export function SolveClock({ pid, running }: { pid: string; running: boolean }) {
  const [secs, setSecs] = useState(() => readSolveSeconds(pid));
  useEffect(() => {
    setSecs(readSolveSeconds(pid));
    if (!running) return;
    let lastInput = Date.now();
    const touch = () => { lastInput = Date.now(); };
    const timer = setInterval(() => {
      if (document.visibilityState !== "visible" || Date.now() - lastInput > IDLE_MS) return;
      const next = readSolveSeconds(pid) + 1;
      try { localStorage.setItem(storageKey(pid), String(next)); } catch { /* ignore */ }
      setSecs(next);
    }, 1000);
    for (const ev of EVENTS) addEventListener(ev, touch, { capture: true, passive: true });
    return () => {
      clearInterval(timer);
      for (const ev of EVENTS) removeEventListener(ev, touch, { capture: true });
    };
  }, [pid, running]);
  if (!running) return null;
  return (
    <span className="clock" title="Time on this problem. It pauses when you leave the tab, or after five minutes without a key or a click.">
      {clockText(secs)}
    </span>
  );
}
