// Shared sheet view state: hover, selection, hint, layers, modes.
// The sheet (canvas, outside React), 3D and the side panel all read it, so it is not React
// state but a small store with subscriptions (useView).

import { useSyncExternalStore } from "react";
import type { WallMode } from "./consts";

export interface Tip {
  key: string;
  x: number;  // px from the top-left corner of the drawing area
  y: number;
}

// What to show: null means everything. Groups count in 3D and on the wiring sheet, the room in 3D
export interface Filter3D {
  groups: Set<string> | null;
  room: string | null;
}

export const shown3d = (f: Filter3D, group: string | null | undefined, room: string | null | undefined) =>
  (!f.groups || !group || f.groups.has(group)) && (!f.room || room === f.room);

// The groups shown after the eye of group g is pressed; all shown again means no filter. all is
// every group of the page, also those with no table row
export function toggledGroups(shown: Set<string> | null, all: string[], g: string): Set<string> | null {
  const on = new Set(shown ?? all);
  if (on.has(g)) on.delete(g); else on.add(g);
  return all.every((k) => on.has(k)) ? null : on;
}

// Elevation layers: electrical (points, boxes, panel, chases, neighbour outlets) and water
export interface WallLayers { electrical: boolean; water: boolean }

// What the electrical sheet shows: sockets with their lines or low voltage (engine/sheet/views.ts)
export type ElectricalView = "sockets" | "low";

export interface ViewState {
  hover: string | null;             // object under the cursor (sheet or 3D)
  lit: Set<string> | null;          // objects of the table row under the cursor
  selected: Set<string> | null;     // the whole selected line
  neighbors: Set<string> | null;    // the rest of the same QF group
  tip: Tip | null;                  // hint at the cursor
  pinned: string | null;            // pinned hint (on click), at the object
  hidden: Set<string>;              // the sheet's own layers switched off, shared by all sheets
  extra: Set<string>;               // layers switched on from other sheets of the drawing (sheet/drawing.ts)
  editMode: boolean;                // "Edit routes"
  show3d: boolean;                  // the wiring sheet in 3D
  wallMode: WallMode;
  filter3d: Filter3D;               // only these QF groups (3D, wiring sheet) and the room (3D)
  themeTick: number;                // the theme changed: recolour
  // Open this sheet right at the object (from an elevation, from a question); around: SheetView.reveal
  goto: { key: string; stage: string; around?: number } | null;
  electricalView: ElectricalView;   // what the electrical sheet shows (engine/sheet/views.ts)
  wallLayers: WallLayers;           // what is visible on the elevation (the eye in the "On the wall" table)
}

type Listener = () => void;

let state: ViewState = {
  hover: null, lit: null, selected: null, neighbors: null, tip: null, pinned: null,
  hidden: new Set(), extra: new Set(), editMode: false, show3d: false, wallMode: "cut",
  filter3d: { groups: null, room: null }, themeTick: 0, goto: null, electricalView: "sockets",
  wallLayers: { electrical: true, water: true },
};
const listeners = new Set<Listener>();

export const view = {
  get: () => state,
  set(patch: Partial<ViewState>) {
    state = { ...state, ...patch };
    for (const l of listeners) l();
  },
  subscribe(l: Listener) {
    listeners.add(l);
    return () => { listeners.delete(l); };
  },
};

export function useView<T>(pick: (s: ViewState) => T): T {
  return useSyncExternalStore(view.subscribe, () => pick(state));
}

// A new sheet: no selection or hint, in its own mode (not 3D, not route editing).
// keep3d means another tab of the same drawing: 3D and its filter stay, the layers change
export function resetSelection(keep3d = false) {
  view.set({
    hover: null, lit: null, selected: null, neighbors: null, tip: null, pinned: null, editMode: false,
    ...(keep3d ? {} : { show3d: false, filter3d: { groups: null, room: null } }),
  });
}
