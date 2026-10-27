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
}

export interface Manifest {
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
  pts: XYZ[];
}

export interface Scene {
  ceiling: number;
  assumed: { ceiling: boolean; openings: string[] };
  floors: { key: string; rings: XY[][] }[];
  walls: { key: string; polys: XY[][][]; z: [number, number]; normals: XY[] }[];
  wires: Record<string, SceneWire>;
  points: Record<string, { pos: XYZ; inward: XY | null; type: string; group: string | null; color: string }>;
  boxes: Record<string, { pos: XYZ; inward: XY | null; label: string; group: string }>;
  board?: { pos: XYZ; inward: XY | null };
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
}
