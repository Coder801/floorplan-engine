// Geometry of the box scheme, px: the wire column (the feed, the box and the fan of cables) and
// the row heights, the same as in BoxScheme.module.scss

export const W = 84, IN_X = 6, BOX_L = 16, BOX = 32, FAN_MID = 66;
export const ROW = 36, ROW_BRIEF = 24;
const MIN_H = 40;  // the box with a margin, when there are one or no cables out

// Height of the fan, the box centre and the row centres for n cables out, rows centred on the box
export function fanLayout(n: number, row: number) {
  const h = Math.max(n * row, MIN_H), top = (h - n * row) / 2;
  return { h, cy: h / 2, ys: Array.from({ length: n }, (_, i) => top + (i + 0.5) * row) };
}
