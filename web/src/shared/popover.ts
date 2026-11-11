// Popup menu at a button ("Download", settings, language): when open, a click outside or Esc
// closes it. ref goes on the wrapper of the button and menu: a click inside it does not close.
// Closing fades: open stays true for FADE_MS with closing set — put data-closing on the panel
// (global.scss), then it is gone

import { useCallback, useEffect, useRef, useState } from "react";
import { REDUCED_MOTION } from "./consts";

export const FADE_MS = 140;  // fade-out of popups (global.scss)

// A popup that fades before it unmounts: shown stays true while closing
export function useFade(ms = FADE_MS) {
  const [shown, setShown] = useState(false);
  const [closing, setClosing] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const live = useRef(false);  // open and not closing
  useEffect(() => () => clearTimeout(timer.current), []);
  const set = useCallback((v: boolean) => {
    if (v === live.current) return;
    live.current = v;
    clearTimeout(timer.current);
    if (v) { setClosing(false); setShown(true); return; }
    if (REDUCED_MOTION) { setShown(false); return; }
    setClosing(true);
    timer.current = setTimeout(() => { setShown(false); setClosing(false); }, ms);
  }, [ms]);
  return { shown, closing, set, live };
}

export function usePopover<T extends HTMLElement>() {
  const { shown: open, closing, set, live } = useFade();
  const ref = useRef<T>(null);
  const setOpen = set;
  useEffect(() => {
    if (!open || closing) return;
    const onDown = (ev: PointerEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) setOpen(false);
    };
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("pointerdown", onDown); window.removeEventListener("keydown", onKey); };
  }, [open, closing, setOpen]);
  return { open, closing, setOpen, toggle: () => setOpen(!live.current), ref };
}
