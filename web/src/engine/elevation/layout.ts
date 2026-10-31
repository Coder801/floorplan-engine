// Раскладка подписей развёртки в px экрана: подписи шкал вдоль оси и плашки номеров у
// символов — без наложений, где получится.

export type Rect = [number, number, number, number];  // x0, y0, x1, y1

// Места подписей вдоль оси: как можно ближе к wanted (по возрастанию), не ближе gap друг
// к другу, в пределах lo…hi, если влезают (как draw_elevations.spread)
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

// Плашка у символа: справа сверху, справа, слева, сверху, снизу, слева сверху — первое
// свободное место (taken дополняется); всё занято — справа сверху
export function badgePlaces(labels: readonly Label[], h: number, taken: Rect[]): Rect[] {
  const gap = 3;
  return labels.map(({ w, anchor: [x0, y0, x1, y1] }) => {
    const cy = (y0 + y1) / 2;
    const options: Rect[] = [
      [x1 + gap, y0 - h + 2, x1 + gap + w, y0 + 2],
      [x1 + gap, cy - h / 2, x1 + gap + w, cy + h / 2],
      [x0 - gap - w, cy - h / 2, x0 - gap, cy + h / 2],
      [(x0 + x1) / 2 - w / 2, y0 - gap - h, (x0 + x1) / 2 + w / 2, y0 - gap],
      [(x0 + x1) / 2 - w / 2, y1 + gap, (x0 + x1) / 2 + w / 2, y1 + gap + h],
      [x0 - gap - w, y0 - h + 2, x0 - gap, y0 + 2],
    ];
    const at = options.find((o) => !taken.some((t) => hit(o, t))) ?? options[0];
    taken.push(at);
    return at;
  });
}
