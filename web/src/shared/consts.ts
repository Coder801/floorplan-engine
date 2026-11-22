// Tab and mode keys and display settings

// Labels live in the i18n dictionaries (src/i18n): only keys here
// Sheet topics of the wall elevations (decision 2026-11-18): each section has its own, with only
// its walls — electrical (with the ceilings) and plumbing
export const WALL_STAGES: ReadonlySet<string> = new Set(["elevations", "plumbing_elevations"]);
export const isWallStage = (stage: string | undefined) => WALL_STAGES.has(stage ?? "");

export const SIDE_TABS = ["tables", "layers"] as const;
// A ceiling (floor) view on the elevations: its lines, the installer notes and tables, layers
export const CEILING_TABS = ["lines", "notes", "layers"] as const;
export type SideTab = (typeof SIDE_TABS)[number] | (typeof CEILING_TABS)[number];
// Not about the sheet: header buttons, a slide-out panel (widgets/Drawer)
export const DRAWER_TABS = ["questions", "sources", "project"] as const;
export type DrawerTab = (typeof DRAWER_TABS)[number];
export const THEMES = ["system", "light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

// The width where the side panel moves under the drawing ($narrow in styles/_mixins.scss)
export const NARROW_PX = 900;
// The width where header actions go into the "⋯" menu ($phone in styles/_mixins.scss)
export const PHONE_PX = 560;

// Sheet PNG for the album: at most A3 at 150 dpi
export const PNG_DPI = 150, PNG_LONG = 2480, PNG_SHORT = 1754;
export const MIN_LINE_PX = 0.6;  // no line is drawn thinner than this on screen
export const SCREEN_BOLD = 1.6;   // engineering lines on screen are this much thicker than on the printed sheet
export const LINE_MIN_PX = 1.5;   // engineering lines on screen are at least this thick (CSS px), at any zoom
export const SYMBOL_GROW = 1.25;  // point and box symbols on screen are this much larger, about their centre
export const TEXT_GROW = 1.6;     // labels and dimension numbers on screen are this much larger, each about its centre (drawing.isLabel)
export const LABEL_BOLD_MM = 0.15; // labels on screen are outlined by this (sheet mm): semi-bold instead of the thin print font
export const STACK_MS = 180;      // a socket stack opening on hover (engine/sheet/stacks.ts)
export const CABLE_MIN_PX = 2;   // wiring lines on screen are at least this thick (0.25 mm on the sheet is under 1 px)
// Layers that exist only on the DXF sheet (frame, title block, tables): not on screen, but in the album PNG
export const SHEET_ONLY = new Set(["A-SHEET", "A-VPORT"]);
export const VIEW_PAD = 16;
export const FIT_SHRINK = 0.93;     // "whole drawing" is 7 % smaller than a tight fit so the labels at the bottom are not cut off
export const TIP_GAP = 12;          // px from the pinned hint to the edge and to the drawing
export const FOCUS_MS = 280;        // duration of zooming to a line
export const NEIGHBOR_ALPHA = 0.75; // neighbours of the selected line by group
export const DIM_ALPHA = 0.12;      // the rest of the wiring during selection

// A selected line in 3D: running dashes from source to target (screen px, px per second)
export const FLOW_DASH_PX = 10, FLOW_GAP_PX = 7, FLOW_SPEED_PX = 32;

// Wiring 3D
export const CUT_HEIGHT_MM = 300;   // near walls in a cut view become a rim of this height
// An exterior wall becomes a rim if its normal into the room faces away from the camera more
// than this (dot product with the view; edge-on keeps full height); a partition is always a rim
export const CUT_DOT = 0.2;
export const WIRE_PX = 3, WIRE_SEL_PX = 4.5, WIRE_LIT_PX = 5;
export const GHOST_ALPHA = 0.3;     // the part of a line hidden by a wall: faint but visible
export const WALL_ALPHA = 1, WALL_GHOST_ALPHA = 0.15;  // solid walls do not blend with the floor
export const WALL_MODES = ["cut", "ghost", "none"] as const;
export type WallMode = (typeof WALL_MODES)[number];

export const REDUCED_MOTION = typeof window !== "undefined"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Panel stickers of a build (out/, sheets/stickers.py)
export const stickersPdf = (colored: boolean, short: boolean) =>
  `panel-stickers${colored ? "-color" : ""}${short ? "-short" : ""}.pdf`;

// What the "Panel" page shows: the panel, the stickers, the groups of the backup bus
export type PanelMode = "front" | "stickers" | "reserve";
