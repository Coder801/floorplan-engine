// The client tour (widgets/Tour): its steps, when a step is there, what it points at and where the
// card stands. Pure functions: the component gives the facts of the project, the screen width and
// the measured rectangles. Anchors are data-tour="…" on existing elements (pages/Viewer,
// widgets/OverviewStage); a step without its anchor on screen drops out, and the counter counts
// the steps that are left.

import { NARROW_PX, PHONE_PX } from "@/shared/consts";

export const STEPS = ["overview", "sheets", "questions", "setup", "help"] as const;
export type TourStep = (typeof STEPS)[number];

// What the project gives the client: the tour does not count these itself
export interface TourFacts {
  sheets: boolean;         // the project has sheet tabs
  canAnswer: boolean;      // can.answer
  openQuestions: number;   // unresolved questions the client sees (the API sends only theirs)
  canChoose: boolean;      // can.choose_variant
  setupTotal: number;      // decisions in the setup wizard (setup.total)
}

export function stepAllowed(step: TourStep, f: TourFacts): boolean {
  if (step === "sheets") return f.sheets;
  if (step === "questions") return f.canAnswer && f.openQuestions > 0;
  if (step === "setup") return f.canChoose && f.setupTotal > 0;
  return true;
}

// The element a step points at: its data-tour value; inMenu — the questions are behind "⋯"
export interface Anchor { key: string; inMenu: boolean }

export const isNarrow = (width: number) => width <= NARROW_PX;  // as @media (max-width: $narrow)

export function anchorOf(step: TourStep, width: number): Anchor {
  // A phone keeps the header actions in the "⋯" menu: the tour shows "⋯" and does not open it
  if (step === "questions" && width <= PHONE_PX) return { key: "questions-menu", inMenu: true };
  // A wide screen has "Set up the project" in the side panel, a narrow one in the overview header
  if (step === "setup" && isNarrow(width)) return { key: "setup-page", inMenu: false };
  return { key: step, inMenu: false };
}

// The step shown at or after index from (in STEPS), having shown `shown` steps already.
// present says whether a step is there now (its condition and its anchor on screen)
export interface Place { step: TourStep; index: number; n: number; total: number }

export function placeAt(from: number, shown: number, present: (step: TourStep) => boolean): Place | null {
  const left = STEPS.slice(from).filter(present);
  if (!left.length) return null;
  return { step: left[0], index: STEPS.indexOf(left[0]), n: shown + 1, total: shown + left.length };
}

export interface Box { left: number; top: number; width: number; height: number }

export const CUT_PAD = 4;   // the cutout around the anchor
export const GAP = 12;      // between the cutout and the card
export const EDGE = 8;      // the card keeps off the screen edge
export const INSIDE = 16;   // the card inside the cutout (step 1)

// The cutout: the anchor and 4 px around it
export const cutout = (r: Box): Box =>
  ({ left: r.left - CUT_PAD, top: r.top - CUT_PAD, width: r.width + 2 * CUT_PAD, height: r.height + 2 * CUT_PAD });

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, Math.max(lo, hi)));

// Where the card stands on a wide screen (a narrow one puts it at the bottom, full width).
// Step 1 is the whole overview: the card sits in its top left corner. The setup button is in
// the side panel: the card goes to its left. The rest is in the header: under the anchor,
// its right edge at the anchor's, or to the left if there is no room below
export function cardSpot(step: TourStep, cut: Box, card: { width: number; height: number },
                         screen: { width: number; height: number }): { left: number; top: number } {
  const maxLeft = screen.width - card.width - EDGE, maxTop = screen.height - card.height - EDGE;
  if (step === "overview") {
    return { left: clamp(cut.left + INSIDE, EDGE, maxLeft), top: clamp(cut.top + INSIDE, EDGE, maxTop) };
  }
  const below = cut.top + cut.height + GAP;
  if (step !== "setup" && below + card.height <= screen.height - EDGE) {
    return { left: clamp(cut.left + cut.width - card.width, EDGE, maxLeft), top: below };
  }
  return { left: clamp(cut.left - GAP - card.width, EDGE, maxLeft), top: clamp(cut.top, EDGE, maxTop) };
}

// The veil with a hole for the cutout: the whole screen and the cutout rect, even-odd, so the
// blur and the shade stay outside and the real element shows sharp. The same number of points
// on every step, so the hole moves with a transition
export const hole = (b: Box) => {
  const l = `${b.left}px`, t = `${b.top}px`, r = `${b.left + b.width}px`, bt = `${b.top + b.height}px`;
  return `polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, ${l} ${t}, ${l} ${bt}, ${r} ${bt}, ${r} ${t}, ${l} ${t})`;
};
