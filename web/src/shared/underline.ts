// The line under the active tab: it is placed under the new tab and "cut in" there by a CSS
// animation (Viewer.module.scss, cut-in), it does not slide from the old one. The tab bar marks
// the active button with aria-current="page"; the line is an absolutely placed element inside
// the bar (position: relative). `cut` changes when the active tab changes: used as the React key
// of the line, it restarts the animation. A resize or a font load re-measures without a new cut

import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

export interface Under { x: number; y: number; w: number }

// Where the line goes: under the button, at its bottom edge (a wrapped bar has rows)
export const underOf = (b: { offsetLeft: number; offsetTop: number; offsetWidth: number; offsetHeight: number }, height = 3): Under =>
  ({ x: b.offsetLeft, y: b.offsetTop + b.offsetHeight - height, w: b.offsetWidth });

export function useUnderline<T extends HTMLElement>(active: unknown) {
  const ref = useRef<T>(null);
  const [at, setAt] = useState<Under | null>(null);
  useLayoutEffect(() => {
    const bar = ref.current;
    if (!bar) return;
    const measure = () => {
      const on = bar.querySelector<HTMLElement>("[aria-current='page']");
      setAt(on ? underOf(on) : null);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(bar);
    void document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [active]);
  const style: CSSProperties | undefined = at
    ? { transform: `translate(${at.x}px, ${at.y}px)`, width: at.w }
    : { display: "none" };
  return { ref, style, cut: String(active) };
}
