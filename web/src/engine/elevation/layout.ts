// Layout of elevation labels in screen px: scale labels along an axis and number badges next
// to symbols, without overlaps where possible (off the cables: a moved label gets a leader).

export type Rect = [number, number, number, number];  // x0, y0, x1, y1

// Label spots along an axis: as close to wanted as possible (ascending), at least gap apart,
// within lo…hi if they fit (like draw_elevations.spread)
export function spread(wanted: readonly number[], gap: number, lo: number, hi: number): number[] {
  const out: number[] = [];
  for (const w of wanted) out.push(out.length ? Math.max(w, lo, out[out.length - 1] + gap) : Math.max(w, lo));
  if (out.length && out[out.length - 1] > hi) {
    out[out.length - 1] = hi;
    for (let k = out.length - 2; k >= 0; k--) out[k] = Math.min(out[k], out[k + 1] - gap);
  }
  return out;
}

const hit = (a: Rect, b: Rect) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

export interface Label { w: number; anchor: Rect }
// A label spot; far: moved off its symbol (cables or other labels were in the way), so it
// gets a dashed leader to the anchor
export interface Place { at: Rect; far: boolean }

const RINGS = 6;  // how far a label may go from its symbol, in label heights

// Badge next to a symbol: top right, right, left, top, bottom, top left; then further out, ring
// by ring (right, left, up, down, the corners), the first free spot (taken is updated); if all
// are taken, top right. With bounds (the wall) a label stays within them
export function badgePlaces(labels: readonly Label[], h: number, taken: Rect[], bounds?: Rect): Place[] {
  const gap = 3;
  return labels.map(({ w, anchor: [x0, y0, x1, y1] }) => {
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const near: Rect[] = [
      [x1 + gap, y0 - h + 2, x1 + gap + w, y0 + 2],
      [x1 + gap, cy - h / 2, x1 + gap + w, cy + h / 2],
      [x0 - gap - w, cy - h / 2, x0 - gap, cy + h / 2],
      [cx - w / 2, y0 - gap - h, cx + w / 2, y0 - gap],
      [cx - w / 2, y1 + gap, cx + w / 2, y1 + gap + h],
      [x0 - gap - w, y0 - h + 2, x0 - gap, y0 + 2],
    ];
    const free = (o: Rect) => !taken.some((t) => hit(o, t))
      && (!bounds || (o[0] >= bounds[0] && o[1] >= bounds[1] && o[2] <= bounds[2] && o[3] <= bounds[3]));
    let place: Place = { at: near.find(free) ?? near[0], far: false };
    if (!near.some(free)) {
      for (let k = 1; k <= RINGS; k++) {
        const d = gap + k * h;
        const far: Rect[] = [
          [x1 + d, cy - h / 2, x1 + d + w, cy + h / 2],
          [x0 - d - w, cy - h / 2, x0 - d, cy + h / 2],
          [cx - w / 2, y0 - d - h, cx + w / 2, y0 - d],
          [cx - w / 2, y1 + d, cx + w / 2, y1 + d + h],
          [x1 + d, y0 - d - h, x1 + d + w, y0 - d],
          [x0 - d - w, y0 - d - h, x0 - d, y0 - d],
          [x1 + d, y1 + d, x1 + d + w, y1 + d + h],
          [x0 - d - w, y1 + d, x0 - d, y1 + d + h],
        ];
        const at = far.find(free);
        if (at) { place = { at, far: true }; break; }
      }
    }
    taken.push(place.at);
    return place;
  });
}

// Leader from a moved label to its anchor: from the nearest point of the label box to the
// anchor centre
export function leader([x0, y0, x1, y1]: Rect, [a0, b0, a1, b1]: Rect): [number, number, number, number] {
  const ax = (a0 + a1) / 2, ay = (b0 + b1) / 2;
  return [Math.min(Math.max(ax, x0), x1), Math.min(Math.max(ay, y0), y1), ax, ay];
}

// Door handle on an elevation: a mark, not a size; on the free edge of the leaf, away from the hinges
export const HANDLE = { height: 1000, inset: 60, end: 180 };

export function handleSpan(x0: number, x1: number, hinge: "start" | "end"): [number, number] {
  return hinge === "start" ? [x1 - HANDLE.inset, x1 - HANDLE.end] : [x0 + HANDLE.inset, x0 + HANDLE.end];
}
