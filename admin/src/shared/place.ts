// Where a floating box goes, fixed to the screen: a button's tooltip under it (centred), an
// in-place confirmation under it (right edge on the button's right edge). Above the button when
// there is no room below; always on the screen. Fixed, so it never moves the table it sits in.

export interface Rect { left: number; right: number; top: number; bottom: number }
export type Place = { left?: number; right?: number; top?: number; bottom?: number; maxWidth?: number };

const GAP = 6;
const EDGE = 8;
const TIP_ROOM = 48;           // the height a tooltip needs below the button
const POP_ROOM = 110;          // the height a confirmation needs below the button

const vertical = (r: Rect, height: number, room: number) =>
  height - r.bottom < room && r.top > height - r.bottom ? { bottom: height - r.top + GAP } : { top: r.bottom + GAP };

/** A tooltip of the measured width tip: centred under the button, inside the screen. */
export function tipPlace(r: Rect, tip: number, width: number, height: number): Place {
  const left = Math.max(EDGE, Math.min((r.left + r.right - tip) / 2, width - tip - EDGE));
  return { left, ...vertical(r, height, TIP_ROOM) };
}

/** A confirmation: its right edge on the button's right edge, as wide as there is room on the left. */
export function popPlace(r: Rect, width: number, height: number): Place {
  const right = Math.max(EDGE, width - r.right);
  return { right, maxWidth: Math.max(160, width - right - EDGE), ...vertical(r, height, POP_ROOM) };
}
