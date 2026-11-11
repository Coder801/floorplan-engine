// Where a button tooltip goes: under the element, centred on it, above it if there is no room
// below; it stays on the screen

export const WIDTH = 260;  // the tooltip's max-width
const GAP = 8;
const EDGE = 8;
const ROOM = 96;  // the height a tooltip needs below the element, or it goes above

interface Rect { left: number; right: number; top: number; bottom: number }

export function below(r: Rect, width: number, height: number) {
  const centre = (r.left + r.right) / 2;
  const left = Math.max(EDGE, Math.min(centre - WIDTH / 2, width - WIDTH - EDGE));
  return height - r.bottom < ROOM ? { left, bottom: height - r.top + GAP } : { left, top: r.bottom + GAP };
}
