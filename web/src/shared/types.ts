// Типы ответов API просмотра (service/viewer.py) и страницы .epd (docs/epd-format.md)

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
  name: string;
  title: string;
  built: number | null;
  stale: boolean;
  stages: Stage[];
  open_questions: number;
  preview: boolean;  // есть out/preview.svg — превью плана из модели
}

export interface Project extends ProjectSummary {
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
  stage?: string;  // тема листа; «points» — ведомость для печати, вкладки нет; «elevations» — развёртки
}

export interface Manifest {
  version: number;  // версия формата .epd (version.ts, FORMAT_VERSION)
  pages: ManifestPage[];
}

// --- Страница .epd ---

export interface Item {
  k: "s" | "f";
  c: string;
  w?: number;
  l: string;
  o?: string;
  d: string;
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
  hint?: string;          // пояснение к строке (смета): значок «i» у наименования
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
  room?: string;  // помещение цели — для фильтра
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
}

// --- Щит в лицо (ключ panel страницы листа «Щит») ---

export interface PanelModel {
  id: string;           // «generic.breaker»
  brand: string;
  series: string;
  modules: number;
  width: number;        // мм
  height: number;       // мм
  style: string;        // как рисовать: breaker, diff, rcd, relay, spd, changeover, ats, input, feed
  body: string;
  lever: string;
  accent?: string;
}

export interface PanelDevice {
  id: string;           // QS1, KV1, QF4…
  key: string;          // device:QF4 — как ключи строк таблиц
  kind: string;
  label: string;        // на аппарате: «C16 30 мА»
  title: string;
  model: PanelModel;
  group?: string;
  feeds?: string[];
  assumed?: boolean;
  reserve?: boolean;
}

export interface PanelGroup {
  purpose: string;
  purpose_assumed: boolean;
  cable: string;
  power: number;        // Вт
  current: number;      // А
  assumed: boolean;
  loads: number;
  color: string | null;
  split_of: string | null;  // линия перегруженной группы, разделённой на щите (QF8.2)
}

export interface PanelData {
  name: string;
  phases: number;
  scheme: "economy" | "standard" | "premium";
  input: { label: string; assumed: boolean };
  devices: PanelDevice[];
  groups: Record<string, PanelGroup>;
  totals: { installed: number; demand: number; calculated: number; current: number; modules: number };
  warnings: { severity: string; text: string; group: string | null }[];
  texts: { title: string; grid: string; reserve: string };
  external?: { id: string; kind: string; title: string; to: string; feed: string | null };
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
  estimate?: SideTable;  // смета — на странице проводки (вкладка «Смета», side.estimate_side_table)
  elevations?: Elevation[];
}

// Развёртки данными (ключ elevations страниц «Развёртки», elevations.elevation_data):
// мм стены — x от левого угла (вид изнутри), y от пола
export interface ElevPoint {
  id: string;
  key: string;            // point:<id> — как на листах электрики и проводки
  n: number;              // номер на листе электрики
  type: string;
  name: string;
  x: number;
  y: number;
  posts: number;
  group: string | null;
  color: string | null;   // цвет группы, как линии проводки
  from: string | null;    // откуда линия проводки: коробка «К3» или щит
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

// Что на стене — у развёртки и у соседней стены в углу (ElevSide)
export interface ElevWall {
  key: string;            // elevation:<комната>.<стена>
  length: number;
  openings: { kind: string; x0: number; x1: number; y0: number; y1: number; assumed: boolean }[];
  chases: { x: number; y0: number; y1: number; wide: boolean; low: boolean }[];
  boxes: ElevBox[];
  points: ElevPoint[];
  board?: { key: string; name: string; x: number; y: number; width: number; height: number };
}

// Соседняя стена в углу: внутренний угол (90 — видна вместе с развёрткой) и что на ней
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
  face?: [XY, XY];        // внутренняя грань на плане (мм модели): начало — левый угол
  left?: ElevSide;        // сосед у левого угла (предыдущая по обходу)
  right?: ElevSide;       // сосед у правого угла (следующая)
}
