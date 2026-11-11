// Transition between drawings (tabs of the header, pages of a sheet): the drawing fades under a
// curtain in the paper colour with the loading mark, the switch happens under it, the curtain
// fades away once the new sheet is loaded and drawn. Walls of the elevations turn without it.
//   idle → in (fade, then the switch) → hold (while loading, at least HOLD_MS) → out → idle

import { useCallback, useEffect, useRef, useState } from "react";
import { REDUCED_MOTION } from "./consts";

export const CURTAIN_IN_MS = 160;
export const CURTAIN_HOLD_MS = 200;   // the mark is on screen at least this long: no blink
export const CURTAIN_OUT_MS = 220;
export const CURTAIN_GIVE_UP_MS = 15000;  // loading hangs: the curtain goes anyway (the error shows)

export type CurtainPhase = "idle" | "in" | "hold" | "out";

// How long the curtain still holds once loading is over
export const holdLeft = (heldAt: number, now: number, min = CURTAIN_HOLD_MS) => Math.max(0, heldAt + min - now);

export function useCurtain(busy: boolean, motion = !REDUCED_MOTION) {
  const [phase, setPhase] = useState<CurtainPhase>("idle");
  const heldAt = useRef(0);
  const timers = useRef<number[]>([]);
  const later = (ms: number, f: () => void) => { timers.current.push(window.setTimeout(f, ms)); };
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  // Run a switch under the curtain; without motion, or with the curtain already up, at once
  const go = useCallback((change: () => void) => {
    if (!motion || phase !== "idle") { change(); return; }
    setPhase("in");
    later(CURTAIN_IN_MS, () => { change(); heldAt.current = performance.now(); setPhase("hold"); });
  }, [motion, phase]);

  // Loaded: wait out the minimum, give the canvas two frames to draw, then lift
  useEffect(() => {
    if (phase !== "hold") return;
    const lift = () => { setPhase("out"); later(CURTAIN_OUT_MS, () => setPhase("idle")); };
    if (busy) { const t = window.setTimeout(lift, CURTAIN_GIVE_UP_MS); return () => clearTimeout(t); }
    let f = 0;
    const t = window.setTimeout(() => { f = requestAnimationFrame(() => { f = requestAnimationFrame(lift); }); },
                                holdLeft(heldAt.current, performance.now()));
    return () => { clearTimeout(t); cancelAnimationFrame(f); };
  }, [phase, busy]);

  return { phase, go };
}
