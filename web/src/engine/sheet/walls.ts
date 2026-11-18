// Elevations page by page: one viewer page is one wall. A printed sheet has many elevations
// (sheets.elevations_spec), but each is tagged with its own object elevation:<room>.<wall>
// (ids.tagged): that gives its bounding box, and the drawing shows only that.
// When elevation data exists (page key elevations), the wall is drawn from it in its own
// canvas (ElevationStage); sheet primitives are only for print and PNG.

import type { Box, CeilingData, Elevation, Page } from "@/shared/types";
import { bbox } from "./paint";

const PAD_MM = 4;  // margin around the elevation, sheet mm

export interface WallPage {
  sheet: number;   // sheet the elevation is on
  key: string;     // elevation:bath.w3
  box: Box;        // bounding box on the sheet, with the margin
  title: string;   // "Санвузол — стіна 3" (object card) or the key
  data?: Elevation;  // elevation as data: what is on the wall
  ceiling?: CeilingData;  // a ceiling (floor) view: its lines for the side panel
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
    const planes = new Map((page.ceilings ?? []).map((c) => [c.key, c]));
    for (const [key, [x0, y0, x1, y1]] of boxes) {
      out.push({
        sheet: index, key, box: [x0 - PAD_MM, y0 - PAD_MM, x1 + PAD_MM, y1 + PAD_MM],
        title: data.get(key)?.title ?? page.objects?.[key]?.title ?? key.slice("elevation:".length),
        ...(data.has(key) ? { data: data.get(key) } : {}),
        ...(planes.has(key) ? { ceiling: planes.get(key) } : {}),
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
// PNG comes from the original sheet. A ceiling (floor) view gets its lanes by group (page.groups),
// so the group eyes of its side panel hide them (filter3d.groups)
export function wallSheet(page: Page, w: WallPage): Page {
  const [x0, y0, x1, y1] = w.box;
  const room = MAP_ROOM * Math.max(x1 - x0, y1 - y0);
  const out: Page = { ...page, items: page.items.filter((it) => !!it.o && ownerOf(it.o) === w.key), view: [x0 - room, y0, x1, y1] };
  if (w.ceiling) out.groups = laneGroups(w.ceiling);
  return out;
}

// The lanes of a ceiling (floor) view by panel group
export function laneGroups(ceiling: CeilingData): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const ln of ceiling.lines) (out[ln.group] ??= []).push(ln.key);
  return out;
}

// A line pinned on a ceiling (floor) view: its lane and the scale values that measure it stay,
// the other lanes and values are dimmed (lookOf); null when the pinned object is not a lane of
// a view on the page. An .epd without dims keeps only the lane
export function laneFocus(page: Page, pinned: string | null): Set<string> | null {
  if (!pinned?.startsWith("lane:")) return null;
  for (const c of page.ceilings ?? []) {
    const ln = c.lines.find((l) => l.key === pinned);
    if (ln) return new Set([ln.key, ...(ln.dims ?? [])]);
  }
  return null;
}

// "Санвузол 2 (пральня) — стіна 2" → room and wall; without " — " the whole name is the wall
export function splitTitle(title: string): [string, string] {
  const k = title.lastIndexOf(" — ");
  return k < 0 ? ["", title] : [title.slice(0, k), title.slice(k + 3)];
}

export interface WallRoom { room: string; items: { index: number; wall: string }[] }

// Walls by room in sheet order (the pager list and the "All walls" overview); a room met again
// later is a new group, as on the sheets. Under the room heading a name stands on its own, so it
// starts with a capital: "Потолок" ("Спальня — потолок" in the title keeps the small letter)
export function wallRooms(walls: readonly { title: string }[]): WallRoom[] {
  const out: WallRoom[] = [];
  walls.forEach((w, index) => {
    const [room, name] = splitTitle(w.title);
    const wall = room ? name.charAt(0).toLocaleUpperCase() + name.slice(1) : name;
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
// (dim:bath.ceiling.x1450, decision 2026-11-12), a box on a ceiling (vbox:bath.ceiling.box_2,
// 2026-11-18) or a line on a ceiling (lane:bath.ceiling.wire_3,
// decision 2026-11-17) — its ceiling (elevation:bath.ceiling); null otherwise
export function ownerOf(o: string): string | null {
  if (o.startsWith("elevation:")) return o;
  const kind = o.startsWith("dim:") ? 4 : o.startsWith("lane:") || o.startsWith("vbox:") ? 5 : 0;
  if (!kind) return null;
  const id = o.slice(kind), k = id.lastIndexOf(".");
  return k < 0 ? null : `elevation:${id.slice(0, k)}`;
}
