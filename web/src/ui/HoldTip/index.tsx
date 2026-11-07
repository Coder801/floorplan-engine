// A tooltip that opens when the pointer stays on an element for HOLD_MS, so a row can be passed over
// without one; it goes when the pointer leaves. A hook, because the element may be a table row:
// the tooltip node goes outside of it, and is fixed to the screen so a scrolled panel does not clip it.

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { place } from "./place";
import css from "./HoldTip.module.scss";

export const HOLD_MS = 2000;

interface Shown { text: string; x: number; y: number }

export function useHoldTip(): {
  start: (text: string, e: ReactPointerEvent) => void;
  move: (e: ReactPointerEvent) => void;
  stop: () => void;
  tip: ReactNode;
} {
  const [shown, setShown] = useState<Shown | null>(null);
  const timer = useRef(0);
  const at = useRef({ x: 0, y: 0 });
  const stop = () => { window.clearTimeout(timer.current); setShown(null); };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const move = (e: ReactPointerEvent) => { at.current = { x: e.clientX, y: e.clientY }; };
  const start = (text: string, e: ReactPointerEvent) => {
    move(e);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setShown({ text, ...at.current }), HOLD_MS);
  };
  const tip = shown && (
    <div role="tooltip" className={css.tip} style={place(shown, window.innerWidth, window.innerHeight)}>{shown.text}</div>
  );
  return { start, move, stop, tip };
}
