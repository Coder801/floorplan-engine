// The line under the active tab (2C): it slides from the old tab to the new one. The tab bar
// marks the active button with aria-current="page"; the line is an absolutely placed element
// inside the bar (position: relative), moved with transform and width and a CSS transition.
// The first placement does not slide; a resize or a font load re-measures

import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

export interface Under { x: number; y: number; w: number }

// Where the line goes: under the button, at its bottom edge (a wrapped bar has rows)
export const underOf = (b: { offsetLeft: number; offsetTop: number; offsetWidth: number; offsetHeight: number }, height = 2): Under =>
  ({ x: b.offsetLeft, y: b.offsetTop + b.offsetHeight - height, w: b.offsetWidth });

export function useUnderline<T extends HTMLElement>(active: unknown) {
  const ref = useRef<T>(null);
  const [at, setAt] = useState<Under | null>(null);
  const [moving, setMoving] = useState(false);  // false until the line has a place: no slide from 0
  useLayoutEffect(() => {
    const bar = ref.current;
    if (!bar) return;
    const measure = () => {
      const on = bar.querySelector<HTMLElement>("[aria-current='page']");
      setAt(on ? underOf(on) : null);
    };
    measure();
    const id = requestAnimationFrame(() => setMoving(true));
    const ro = new ResizeObserver(measure);
    ro.observe(bar);
    void document.fonts?.ready.then(measure);
    return () => { cancelAnimationFrame(id); ro.disconnect(); };
  }, [active]);
  const style: CSSProperties | undefined = at
    ? { transform: `translate(${at.x}px, ${at.y}px)`, width: at.w, transition: moving ? undefined : "none" }
    : { display: "none" };
  return { ref, style };
}
