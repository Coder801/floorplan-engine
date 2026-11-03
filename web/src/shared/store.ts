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

// What to show in 3D: null means everything
export interface Filter3D {
  groups: Set<string> | null;
  room: string | null;
}

export const shown3d = (f: Filter3D, group: string | null | undefined, room: string | null | undefined) =>
  (!f.groups || (!!group && f.groups.has(group))) && (!f.room || room === f.room);

// Elevation layers: electrical (points, boxes, panel, chases, neighbour outlets) and water
export interface WallLayers { electrical: boolean; water: boolean }

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
  filter3d: Filter3D;               // 3D: only these QF groups and the room
  themeTick: number;                // the theme changed: recolour
  goto: string | null;              // open the sheet right at this object (from an elevation to wiring)
  wallLayers: WallLayers;           // what is visible on the elevation (the eye in the "On the wall" table)
}

type Listener = () => void;

let state: ViewState = {
  hover: null, lit: null, selected: null, neighbors: null, tip: null, pinned: null,
  hidden: new Set(), extra: new Set(), editMode: false, show3d: false, wallMode: "cut",
  filter3d: { groups: null, room: null }, themeTick: 0, goto: null,
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
