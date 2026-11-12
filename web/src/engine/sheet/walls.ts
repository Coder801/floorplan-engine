// Elevations page by page: one viewer page is one wall. A printed sheet has many elevations
// (sheets.elevations_spec), but each is tagged with its own object elevation:<room>.<wall>
// (ids.tagged): that gives its bounding box, and the drawing shows only that.
// When elevation data exists (page key elevations), the wall is drawn from it in its own
// canvas (ElevationStage); sheet primitives are only for print and PNG.

import type { Box, Elevation, Page } from "@/shared/types";
import { bbox } from "./paint";

const PAD_MM = 4;  // margin around the elevation, sheet mm

export interface WallPage {
  sheet: number;   // sheet the elevation is on
  key: string;     // elevation:bath.w3
  box: Box;        // bounding box on the sheet, with the margin
  title: string;   // "Санвузол — стіна 3" (object card) or the key
  data?: Elevation;  // elevation as data: what is on the wall
}

// Sheet elevations in order: sheets as passed, on a sheet by the first primitive
export function wallPages(sheets: readonly { index: number; page: Page }[]): WallPage[] {
  const out: WallPage[] = [];
  for (const { index, page } of sheets) {
    const boxes = new Map<string, Box>();
    for (const it of page.items) {
      const key = it.o ? ownerOf(it.o) : null;
      if (!key) continue;
      const [x0, y0, x1, y1] = bbox(it.d);
      const b = boxes.get(key);
      boxes.set(key, b ? [Math.min(b[0], x0), Math.min(b[1], y0), Math.max(b[2], x1), Math.max(b[3], y1)]
        : [x0, y0, x1, y1]);
    }
    const data = new Map((page.elevations ?? []).map((e) => [e.key, e]));
    for (const [key, [x0, y0, x1, y1]] of boxes) {
      out.push({
        sheet: index, key, box: [x0 - PAD_MM, y0 - PAD_MM, x1 + PAD_MM, y1 + PAD_MM],
        title: data.get(key)?.title ?? page.objects?.[key]?.title ?? key.slice("elevation:".length),
        ...(data.has(key) ? { data: data.get(key) } : {}),
      });
    }
  }
  return out;
}

// Left of the elevation, a margin for the flat mini map (WallMap at the bottom left): a share
// of the elevation width, but at least a share of its height: a narrow tall wall has little width
export const MAP_ROOM = 0.32;

// A one-elevation sheet: only its primitives (the margin on the left would show the
// neighbouring elevation), the viewport is its bounding box plus the mini map margin. The album
// PNG comes from the original sheet
export function wallSheet(page: Page, w: WallPage): Page {
  const [x0, y0, x1, y1] = w.box;
  const room = MAP_ROOM * Math.max(x1 - x0, y1 - y0);
  return { ...page, items: page.items.filter((it) => !!it.o && ownerOf(it.o) === w.key), view: [x0 - room, y0, x1, y1] };
}

// "Санвузол 2 (пральня) — стіна 2" → room and wall; without " — " the whole name is the wall
export function splitTitle(title: string): [string, string] {
  const k = title.lastIndexOf(" — ");
  return k < 0 ? ["", title] : [title.slice(0, k), title.slice(k + 3)];
}

export interface WallRoom { room: string; items: { index: number; wall: string }[] }

// Walls by room in sheet order (the pager list and the "All walls" overview); a room met again
// later is a new group, as on the sheets
export function wallRooms(walls: readonly { title: string }[]): WallRoom[] {
  const out: WallRoom[] = [];
  walls.forEach((w, index) => {
    const [room, wall] = splitTitle(w.title);
    const last = out[out.length - 1];
    if (last && last.room === room) last.items.push({ index, wall });
    else out.push({ room, items: [{ index, wall }] });
  });
  return out;
}

// A room's ceiling (decision 2026-11-12) or floor route plane on the elevations sheets: one more
// page of the pager, "elevation:<room>.ceiling" / ".floor"; it has no wall data
export const isPlane = (key: string): boolean => /\.(ceiling|floor)$/.test(key);

// The elevation page an object belongs to: an elevation itself, or a ceiling scale value
// (dim:bath.ceiling.x1450, decision 2026-11-12) — its ceiling (elevation:bath.ceiling); null otherwise
export function ownerOf(o: string): string | null {
  if (o.startsWith("elevation:")) return o;
  if (!o.startsWith("dim:")) return null;
  const id = o.slice(4), k = id.lastIndexOf(".");
  return k < 0 ? null : `elevation:${id.slice(0, k)}`;
}
