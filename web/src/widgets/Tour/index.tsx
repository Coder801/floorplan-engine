// The client tour of the viewer (variant A, "pointer", decision 2026-11-22): the screen is veiled,
// a cutout shows a real element, a card next to it says what it is for. Steps, their conditions
// and where the card stands — steps.ts; once per browser — seen.ts (the caller marks it in
// onClose). The tour switches nothing itself: it opens no sheet, no "⋯" menu, no drawer, only
// shows where things are. The anchor is looked up on every step and on resize or scroll; a step
// whose anchor is gone drops out. A click on the veil or in the cutout does nothing (a missed tap
// must not end the tour); "Skip" and Esc close it on any step. A narrow screen puts the card at
// the bottom, full width, after scrolling the anchor to the middle.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { REDUCED_MOTION } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { Button } from "@/ui/Button";
import { Heading } from "@/ui/Heading";
import { Text } from "@/ui/Text";
import { anchorOf, cardSpot, cutout, hole, isNarrow, placeAt, stepAllowed, type Box, type Place, type TourFacts, type TourStep } from "./steps";
import css from "./Tour.module.scss";

export type { TourFacts } from "./steps";

const FOCUSABLE = "button:not(:disabled), [href]";
const CARD_W = 320, CARD_H = 220;  // the card before it is measured

interface Props {
  facts: TourFacts;
  onClose: () => void;  // any close: "Got it", "Skip", Esc
}

// The anchor element on screen now, or null if it is missing or hidden (display: none has no box)
function anchorEl(step: TourStep, width: number): HTMLElement | null {
  const el = document.querySelector<HTMLElement>(`[data-tour="${anchorOf(step, width).key}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 || r.height > 0 ? el : null;
}

const boxOf = (r: DOMRect): Box => ({ left: r.left, top: r.top, width: r.width, height: r.height });
// A pointer that is a finger: the zoom hint for touch
const coarse = () => typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;

export function Tour({ facts, onClose }: Props) {
  const { t } = useTranslation();
  const [at, setAt] = useState({ from: 0, shown: 0 });  // look from this step, having shown that many
  const [place, setPlace] = useState<Place | null>(null);
  const [cut, setCut] = useState<Box | null>(null);
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight });
  const [cardH, setCardH] = useState(CARD_H);
  const card = useRef<HTMLDivElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  const factsRef = useRef(facts);
  factsRef.current = facts;
  const narrow = isNarrow(size.width);

  // The step: the first one from `at` that is allowed and has its anchor on screen
  useLayoutEffect(() => {
    const width = window.innerWidth;
    const p = placeAt(at.from, at.shown, (s) => stepAllowed(s, factsRef.current) && !!anchorEl(s, width));
    if (!p) { close.current(); return; }
    // A narrow screen: the card covers the bottom, so the anchor goes to the middle first
    if (isNarrow(width)) anchorEl(p.step, width)?.scrollIntoView({ block: "center", behavior: REDUCED_MOTION ? "auto" : "smooth" });
    setPlace(p);
  }, [at]);

  // The cutout follows the anchor: on resize and on any scroll (the page, a panel)
  const measure = useCallback(() => {
    setSize({ width: window.innerWidth, height: window.innerHeight });
    if (!place) return;
    const el = anchorEl(place.step, window.innerWidth);
    setCut(el ? cutout(boxOf(el.getBoundingClientRect())) : null);
  }, [place]);
  useLayoutEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => { window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure, true); };
  }, [measure]);
  useLayoutEffect(() => {
    if (card.current) setCardH(card.current.offsetHeight || CARD_H);
  }, [place, size.width]);

  // Focus on "Next" at every step; Tab stays in the card, Esc closes (as in Modal)
  // Focus is on "Next" for the keyboard, but without the ring: the card was not reached by Tab
  useEffect(() => { next.current?.focus({ preventScroll: true, focusVisible: false } as FocusOptions); }, [place]);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close.current(); return; }
      if (ev.key !== "Tab" || !card.current) return;
      const all = [...card.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!all.length) return;
      const first = all[0], last = all[all.length - 1];
      const inside = card.current.contains(document.activeElement);
      if (ev.shiftKey && (document.activeElement === first || !inside)) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && (document.activeElement === last || !inside)) { ev.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("keydown", onKey, true); before?.focus?.({ preventScroll: true }); };
  }, []);

  if (!place) return null;
  const last = place.n === place.total;
  const goOn = () => (last ? onClose() : setAt({ from: place.index + 1, shown: place.n }));
  const inMenu = place.step === "questions" && anchorOf("questions", size.width).inMenu;
  const body = t(`tour.steps.${place.step}.body`);
  const spot = !narrow && cut ? cardSpot(place.step, cut, { width: CARD_W, height: cardH }, size) : null;
  const id = "tour-title";
  return createPortal(
    // The veil takes every click and does nothing with it
    <div className={css.tour}>
      <div className={css.veil} style={cut ? { clipPath: hole(cut) } : undefined} aria-hidden="true" />
      {cut && <div className={css.cut} style={{ left: cut.left, top: cut.top, width: cut.width, height: cut.height }} aria-hidden="true" />}
      <div ref={card} className={cx(css.card, narrow && css.bottom)} role="dialog" aria-modal="true" aria-labelledby={id}
           style={spot ? { left: spot.left, top: spot.top } : undefined}>
        <Text size="small" tone="muted" mono>{t("tour.stepOf", { n: place.n, total: place.total })}</Text>
        <Heading level={2} size="heading" id={id}>{t(`tour.steps.${place.step}.title`)}</Heading>
        <Text>{inMenu ? `${t("tour.steps.questions.inMenu")} ${body}` : body}</Text>
        {place.step === "sheets" && <Text size="small" tone="muted">{t(coarse() ? "tour.touch" : "tour.mouse")}</Text>}
        <div className={css.buttons}>
          <Button ref={next} variant="primary" size={narrow ? "lg" : "md"} block={narrow} className={css.next} onClick={goOn}>
            {t(last ? "tour.done" : "tour.next")}
          </Button>
          {!last && <Button variant="link" size={narrow ? "lg" : "md"} block={narrow} className={css.skip} onClick={onClose}>{t("tour.skip")}</Button>}
        </div>
      </div>
    </div>,
    document.body,
  );
}
