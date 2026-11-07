// Where a tooltip goes: left of the pointer (the side panel is at the right edge of the screen),
// below it, or above it in the lower half; it stays on the screen

const WIDTH = 280;  // the tooltip's max-width
const GAP = 12;
const EDGE = 8;

export function place({ x, y }: { x: number; y: number }, width: number, height: number) {
  const right = Math.max(EDGE, Math.min(width - x + GAP, width - WIDTH - EDGE));
  return y > height / 2 ? { right, bottom: height - y + GAP } : { right, top: y + GAP };
}
