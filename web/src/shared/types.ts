// Types of the viewer API responses (service/viewer.py) and the .epd page (docs/epd-format.md)

export type XY = [number, number];
export type XYZ = [number, number, number];
export type Box = [number, number, number, number];

export interface Stage {
  stage: string;
  status: string;
  builds?: boolean;
}

export interface Question {
  id: string;
  stage: string;
  severity: string;
  state: string;
  text: string;
  answer: "value" | "choice" | "text";
  options?: string[];
  option_labels?: Record<string, string>;  // how an option reads for a person, in the project language
  also?: string[];
  assumption?: unknown;
  unit?: string;
  target?: string;
}

export interface Issue {
  severity: string;
  file: string;
  path: string;
  message: string;
}

export interface Report {
  questions: Question[];
  issues: Issue[];
}

export interface ProjectSummary {
  // Key of the project in addresses (/api/projects/{id}, #id): the id in the database (projects in
  // the database, docs/database.md), the folder name in the folder viewer
  id: string;
  name: string;  // folder name (slug): shown under the title
  title: string;
  built: number | null;
  stale: boolean;
  stages: Stage[];
  open_questions: number;
  preview: boolean;  // out/preview.svg exists: the plan preview from the model
}

export interface Project extends ProjectSummary {
  // Missing on an old server: everything allowed, except answers (they write nothing there)
  can?: { edit_wiring: boolean; choose_variant: boolean; answer?: boolean };
  report: Report | null;
  answers: Record<string, unknown>;
  artifact: boolean;
  dxf: string | null;
  files: string[];
  sources: string[];
  parsed?: { file: string; note: string }[];
  model: string[];
}

export interface ManifestPage {
  index: number;
  name: string;
  format: string | null;
  size: XY;
  file: string;
  stage?: string;  // sheet topic; "points" is the print schedule, no tab; "elevations" are the elevations
}

export interface Manifest {
  version: number;  // .epd format version (version.ts, FORMAT_VERSION)
  pages: ManifestPage[];
  variants?: Variants;  // wiring variants: the chosen one and a summary of all (pipeline.variant_block)
  overview?: Overview;  // project overview for the "Overview" tab (overview.py)
}

export interface Overview {
  object: { name: string; object: string; building: string; code: string; stage: string; organization: string };
  language: string;
  rooms: { id: string; name: string; area: number; wet: boolean }[];
  area: number;           // m²
  ceiling: { height: number; assumed: boolean };  // mm
  points?: { key: string; text: string; count: number; unit: string }[];
  panel?: {
    scheme: "economy" | "standard" | "premium"; input: string; input_assumed: boolean;
    devices: number; groups: number; modules: number; installed_w: number; calculated_w: number;
  };
  plumbing?: OverviewPlumbing;  // plumbing: fixtures, water, sewer (absent without plumbing.yaml)
}

export interface OverviewPlumbing {
  fixtures: { type: string; text: string; count: number }[];
  water: {
    distribution: "collector" | "tee"; hot: "riser" | "boiler" | null;
    cold_m: number; hot_m: number; outlets: number; input_assumed: boolean;  // m, along routes, without margin
  };
  sewer: { pipes: { d: number; m: number }[]; risers: number; bends: number; tees: number; errors: number };
  weak: number;  // plumbing weak spots
  // Plumbing estimate total (out/plumbing-estimate.*): goes into the project total together with electrical
  estimate?: { total: number; currency: string; unpriced: number };
}

// Wiring variants (docs/wiring-variants.md): mode, route, distribution
export type VariantMode = "economy" | "standard" | "proper";
export type VariantRoute = "ceiling" | "floor";
export type VariantDistribution = "boxes";

export interface VariantSummary {
  key: string;            // «economy-floor-boxes»
  mode: VariantMode;
  route: VariantRoute;
  distribution: VariantDistribution;
  total: number;          // estimate total
  currency: string;
  unpriced: number;
  cable_m: number;
  devices: number;        // devices in the panel
  chases_m: number;
  conduit_m: number;      // conduit along routes
  edited: boolean;        // has manual route edits
}

export interface Variants {
  active: string;         // key of the chosen one
  default: string;        // "as in project"
  items: VariantSummary[];
}

// --- .epd page ---

export interface Item {
  k: "s" | "f";
  c: string;
  w?: number;
  l: string;
  o?: string;
  d: string;
}

// Legend for the viewer badge (key legend of the electrical and lighting pages): the icon is
// the same primitives as on the sheet (sheet mm), and what it means
export interface LegendEntry {
  key: string;     // symbol: socket, switch, board, led_strip…
  text: string;
  items: Item[];
}

export interface ObjectCard {
  title: string;
  rows: [string, string][];
}

export interface TableRow {
  cells: string[];
  keys?: string[];
  color?: string;
  section?: boolean;
  hint?: string;          // row note (estimate): an "i" icon next to the name
  marker?: "square";      // icon without colour: a panel device not on a group line
}

export interface SideTable {
  title: string;
  columns: string[];
  align: string[];
  rows: TableRow[];
  total?: string[];
  notes?: string[];
}

export interface EditWire {
  from: string;
  to: string;
  path: XY[];
  lane?: XY[];
  manual: boolean;
}

export interface EditBox {
  room: string;
  group: string;
  label: string;
  at: XY;
  inward: XY | null;
  size: number;
  span: [XY, XY] | null;
  manual: boolean;
}

export interface SceneWire {
  group: string;
  color: string;
  route: "ceiling" | "floor";
  from: string;
  to: string;
  room?: string;  // target room, for the filter
  pts: XYZ[];
}

export interface Scene {
  ceiling: number;
  assumed: { ceiling: boolean; openings: string[] };
  floors: { key: string; rings: XY[][] }[];
  walls: { key: string; polys: XY[][][]; z: [number, number]; normals: XY[] }[];
  wires: Record<string, SceneWire>;
  points: Record<string, { pos: XYZ; inward: XY | null; type: string; room?: string; group: string | null; color: string }>;
  boxes: Record<string, { pos: XYZ; inward: XY | null; label: string; room?: string; group: string }>;
  board?: { pos: XYZ; inward: XY | null };
  // Plumbing (epd/plumbing.plumbing_scene): pipes by height, supplies on the wall, risers
  pipes?: Record<string, ScenePipe>;
  fixtures?: Record<string, { key: string; kind: PipeKind; color: string; pos: XYZ; inward: XY; room?: string }>;
  risers?: { key: string; pos: XY; r: number; z: [number, number]; room?: string }[];
}

export type PipeKind = "cold" | "hot" | "sewer";

export interface ScenePipe {
  key: string;      // pipe:<id>
  kind: PipeKind;
  d: number;        // Ø, mm
  color: string;
  room?: string;
  pts: XYZ[];
}

// --- Panel front view (key panel of the "Panel" sheet page) ---

export interface PanelModel {
  id: string;           // «generic.breaker»
  brand: string;
  series: string;
  modules: number;
  width: number;        // mm
  height: number;       // mm
  style: string;        // how to draw: breaker, diff, rcd, relay, spd, changeover, ats, input, feed
  body: string;
  lever: string;
  accent?: string;
}

// Panel enclosure from the catalogue (panel_catalog.Enclosure): a real panel, mm
export interface PanelEnclosure {
  id: string;           // "hager.VS212PD"; an on-site one is "fitted.3x24"
  brand: string;
  series: string;
  article: string;      // article; empty for an on-site enclosure
  title: string;        // «Hager Golf VS212PD»
  rows: number;
  per_row: number;      // modules per rail
  width: number;
  height: number;
  depth: number;
  pitch: number;        // rail step
  body: string;
}

export interface PanelDevice {
  id: string;           // QS1, KV1, QF4…
  key: string;          // device:QF4, like the table row keys
  kind: string;
  label: string;        // on the device: "C16 30 мА"
  title: string;
  model: PanelModel;
  group?: string;
  feeds?: string[];
  assumed?: boolean;
  reserve?: boolean;
  row?: number;         // enclosure rail from the top, from 0
}

export interface PanelGroup {
  purpose: string;
  purpose_assumed: boolean;
  cable: string;
  power: number;        // W
  current: number;      // A
  assumed: boolean;
  loads: number;
  color: string | null;
  split_of: string | null;  // a line of an overloaded group split on the panel (QF8.2)
}

// Device stickers (key panel.stickers, sheets/stickers.py): sizes in mm, text as curves
export interface PanelSticker {
  id: string;           // QF12
  row: number;          // rail
  title: string;        // full purpose
  icon: string;         // key in icons
  text: string;         // number and name as one SVG path, in sticker mm
}

export interface PanelStickers {
  width: number;
  height: number;
  pad: number;
  rule_y: number;
  icon: { x: number; y: number; size: number; stroke: number };
  items: PanelSticker[];
  icons: Record<string, string[]>;  // SVG paths in a 24-unit box
}

// Battery box at a hybrid inverter (key panel.dc): battery breaker, solar strings
export interface PanelDc {
  enclosure: PanelEnclosure;
  devices: PanelDevice[];
  battery: { voltage: number; voltage_assumed: boolean; capacity: number | null; power: number;
             power_assumed: boolean; current: number; rating: number; cable: number };
  pv_strings: number;
  texts: { title: string; battery: string; pv: string; kwh?: string };  // kwh is missing in an old .epd
}

export interface PanelData {
  name: string;
  phases: number;
  scheme: "economy" | "standard" | "premium";
  input: { label: string; assumed: boolean };
  enclosure?: PanelEnclosure | null;  // missing means an on-site enclosure (old .epd)
  devices: PanelDevice[];
  groups: Record<string, PanelGroup>;
  totals: { installed: number; demand: number; calculated: number; current: number; modules: number };
  warnings: { severity: string; text: string; group: string | null }[];
  stickers?: PanelStickers;  // an older .epd has none
  texts: { title: string; grid: string; reserve: string };
  // to is where LOAD arrives (the QS3 output breaker or the switch directly), switch is the ATS
  // KM1 or the switch SA1: from QS3 into its input II
  external?: { id: string; kind: string; title: string; to: string; switch?: string; feed: string | null };
  dc?: PanelDc;
}

export interface Page {
  name: string;
  format: string | null;
  size: XY;
  background: string;
  items: Item[];
  view?: Box;
  model?: [number, number, number];
  stage?: string;
  tables?: SideTable[];
  objects?: Record<string, ObjectCard>;
  chains?: Record<string, string[]>;
  groups?: Record<string, string[]>;
  edit?: { wires: Record<string, EditWire>; boxes: Record<string, EditBox> };
  scene?: Scene;
  panel?: PanelData;
  estimate?: SideTable;  // the estimate is on the wiring page ("Estimate" tab, side.estimate_side_table)
  elevations?: Elevation[];
  legend?: LegendEntry[];  // the legend is a badge on the drawing (widgets/Legend)
}

// Elevations as data (key elevations of the "Elevations" pages, elevations.elevation_data):
// wall mm, x from the left corner (view from inside), y from the floor
export interface ElevPoint {
  id: string;
  key: string;            // point:<id>, as on the electrical and wiring sheets
  n: number;              // number on the electrical sheet
  type: string;
  name: string;
  x: number;
  y: number;
  posts: number;
  group: string | null;
  color: string | null;   // group colour, like the wiring lines
  from: string | null;    // where the wiring line comes from: box "К3" or the panel
}

export interface ElevBox {
  id: string;
  key: string;            // box:<id>
  label: string;
  x: number;
  y: number;
  size: number;
  group: string | null;
  color: string | null;
  from: string | null;
}

// What is on the wall, for the elevation and the neighbouring wall at a corner (ElevSide)
// Water outlet or drain on the wall: key is the fixture (fixture:<id>), name the fixture in words
export interface ElevWater {
  fixture: string; key: string; name: string; n: number; kind: PipeKind;
  x: number; y: number; d: number; assumed: boolean;
}

export interface ElevWall {
  key: string;            // elevation:<room>.<wall>
  length: number;
  openings: { kind: string; x0: number; x1: number; y0: number; y1: number; assumed: boolean }[];
  chases: { x: number; y0: number; y1: number; wide: boolean; low: boolean }[];
  boxes: ElevBox[];
  points: ElevPoint[];
  board?: { key: string; name: string; x: number; y: number; width: number; height: number };
  // Plumbing water outlets and drains: n is the fixture number on the "Plumbing" sheet
  water?: ElevWater[];
}

// Neighbouring wall at a corner: the inner angle (90 means visible together with the elevation) and what is on it
export interface ElevSide extends ElevWall {
  turn: number;
}

export interface Elevation extends ElevWall {
  title: string;
  behind: string;
  height: number;
  height_assumed: boolean;
  top: number;
  back: { id: string; n: number; type: string; x: number; y: number; posts: number }[];
  face?: [XY, XY];        // inner face on the plan (model mm): starts at the left corner
  left?: ElevSide;        // neighbour at the left corner (previous in the walk)
  right?: ElevSide;       // neighbour at the right corner (next)
}

// Studio price page (GET /api/prices, pipeline.price_page): electrical works, the studio price
// (prices.yaml next to the projects) and the market spread (market.yaml)
export interface MarketQuote { source: string; price: number; text: string }
export interface MarketSpread {
  n: number; min: number; q1: number; median: number; q3: number; max: number;
  basis: string;              // what is compared: wall material, unit
  quotes: MarketQuote[];      // by price, cheapest first
}
export interface PriceRow {
  key: string;                // estimate item key, work.*
  section: "rough" | "finish";
  unit: string;
  name: { ru: string; uk: string };
  hint: { ru: string; uk: string } | null;
  price: number | null;       // studio price; null — none in prices.yaml
  service: number | null;     // no studio price: the price service's one (a mock for now)
  market: MarketSpread | null;
}
// Period of market prices: "YYYY" or "YYYY-MM"; no dated sources — empty strings
export interface MarketPeriod { start: string; end: string; dated: number; undated: number }
export interface MarketSource {
  id: string; name: string; url: string; date: string;
  kind: "company" | "master" | "platform" | "review"; note: string;
}
export interface PricePage {
  file: string;
  exists: boolean;
  currency: string;
  date: string;
  note: string;
  rows: PriceRow[];
  market: { region: string; collected: string; currency: string; period: MarketPeriod; sources: MarketSource[] } | null;
  issues: string[];
  editable: boolean;
}
