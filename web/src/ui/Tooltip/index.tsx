// A tooltip for buttons: opens when the mouse stays on a button for DELAY_MS or the button gets
// keyboard focus, closes when it leaves, on blur and on a click. A hook, not a wrapper, so a
// button keeps its place in a segmented control (`> button` styles): spread `on(text)` on each
// button and render `tip` once. The tooltip is fixed to the screen under the button (place.ts).

import { useEffect, useId, useRef, useState, type FocusEvent, type PointerEvent, type ReactNode } from "react";
import { below } from "./place";
import css from "./Tooltip.module.scss";

export const DELAY_MS = 400;

interface Shown { text: string; at: ReturnType<typeof below> }

export function useTooltip(): {
  on: (text: string) => {
    onPointerEnter: (e: PointerEvent<HTMLElement>) => void;
    onPointerLeave: () => void;
    onFocus: (e: FocusEvent<HTMLElement>) => void;
    onBlur: () => void;
    onPointerDown: () => void;
    "aria-describedby": string | undefined;
  };
  tip: ReactNode;
} {
  const [shown, setShown] = useState<Shown | null>(null);
  const timer = useRef(0);
  const id = useId();
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const hide = () => { window.clearTimeout(timer.current); setShown(null); };
  const show = (text: string, el: HTMLElement) =>
    setShown({ text, at: below(el.getBoundingClientRect(), window.innerWidth, window.innerHeight) });
  const on = (text: string) => ({
    onPointerEnter: (e: PointerEvent<HTMLElement>) => {
      if (e.pointerType !== "mouse") return;
      const el = e.currentTarget;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => show(text, el), DELAY_MS);
    },
    onPointerLeave: hide,
    onFocus: (e: FocusEvent<HTMLElement>) => { if (e.currentTarget.matches(":focus-visible")) show(text, e.currentTarget); },
    onBlur: hide,
    onPointerDown: hide,
    "aria-describedby": shown?.text === text ? id : undefined,
  });
  const tip = shown && <div id={id} role="tooltip" data-pop="" className={css.tip} style={shown.at}>{shown.text}</div>;
  return { on, tip };
}
