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
  can?: { edit_wiring: boolean; choose_variant: boolean };  // нет — старый сервер: всё можно
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
  variants?: Variants;  // варианты проводки: выбранный и сводка всех (pipeline.variant_block)
  overview?: Overview;  // общие сведения о проекте — вкладка «Общие сведения» (overview.py)
}

export interface Overview {
  object: { name: string; object: string; building: string; code: string; stage: string; organization: string };
  language: string;
  rooms: { id: string; name: string; area: number; wet: boolean }[];
  area: number;           // м²
  ceiling: { height: number; assumed: boolean };  // мм
  points?: { key: string; text: string; count: number; unit: string }[];
  panel?: {
    scheme: "economy" | "standard" | "premium"; input: string; input_assumed: boolean;
    devices: number; groups: number; modules: number; installed_w: number; calculated_w: number;
  };
  plumbing?: OverviewPlumbing;  // сантехника: приборы, вода, канализация (нет plumbing.yaml — нет)
}

export interface OverviewPlumbing {
  fixtures: { type: string; text: string; count: number }[];
  water: {
    distribution: "collector" | "tee"; hot: "riser" | "boiler" | null;
    cold_m: number; hot_m: number; outlets: number; input_assumed: boolean;  // м — по трассам, без запаса
  };
  sewer: { pipes: { d: number; m: number }[]; risers: number; bends: number; tees: number; errors: number };
  weak: number;  // слабых мест сантехники
  // Итог сметы сантехники (out/plumbing-estimate.*): в итоге проекта вместе с электрикой
  estimate?: { total: number; currency: string; unpriced: number };
}

// Варианты проводки (docs/wiring-variants.md): режим, трасса, разводка
export type VariantMode = "economy" | "standard" | "proper";
export type VariantRoute = "ceiling" | "floor";
export type VariantDistribution = "boxes";

export interface VariantSummary {
  key: string;            // «economy-floor-boxes»
  mode: VariantMode;
  route: VariantRoute;
  distribution: VariantDistribution;
  total: number;          // всего по смете
  currency: string;
  unpriced: number;
  cable_m: number;
  devices: number;        // аппаратов в щите
  chases_m: number;
  conduit_m: number;      // гофра по трассам
  edited: boolean;        // есть ручные правки трасс
}

export interface Variants {
  active: string;         // ключ выбранного
  default: string;        // «как в проекте»
  items: VariantSummary[];
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

// Легенда для плашки просмотра (ключ legend страниц электрики и освещения): значок — те же
// примитивы, что на листе (мм листа), и что он значит
export interface LegendEntry {
  key: string;     // символ: socket, switch, board, led_strip…
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
  hint?: string;          // пояснение к строке (смета): значок «i» у наименования
  marker?: "square";      // значок без цвета: аппарат щита не на линии группы
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
  // Сантехника (epd/plumbing.plumbing_scene): трубы по высоте, подводы на стене, стояки
  pipes?: Record<string, ScenePipe>;
  fixtures?: Record<string, { key: string; kind: PipeKind; color: string; pos: XYZ; inward: XY; room?: string }>;
  risers?: { key: string; pos: XY; r: number; z: [number, number]; room?: string }[];
}

export type PipeKind = "cold" | "hot" | "sewer";

export interface ScenePipe {
  key: string;      // pipe:<id>
  kind: PipeKind;
  d: number;        // Ø, мм
  color: string;
  room?: string;
  pts: XYZ[];
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

// Корпус щита из каталога (panel_catalog.Enclosure): реальный щит, мм
export interface PanelEnclosure {
  id: string;           // «hager.VS212PD»; подобранный по месту — «fitted.3x24»
  brand: string;
  series: string;
  article: string;      // артикул; у подобранного по месту — пусто
  title: string;        // «Hager Golf VS212PD»
  rows: number;
  per_row: number;      // модулей в рейке
  width: number;
  height: number;
  depth: number;
  pitch: number;        // шаг реек
  body: string;
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
  row?: number;         // рейка корпуса сверху, с 0
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

// Щит АКБ у гибридного инвертора (ключ panel.dc): автомат АКБ, строки солнечных панелей
export interface PanelDc {
  enclosure: PanelEnclosure;
  devices: PanelDevice[];
  battery: { voltage: number; voltage_assumed: boolean; capacity: number | null; power: number;
             power_assumed: boolean; current: number; rating: number; cable: number };
  pv_strings: number;
  texts: { title: string; battery: string; pv: string; kwh?: string };  // kwh — нет в старом .epd
}

export interface PanelData {
  name: string;
  phases: number;
  scheme: "economy" | "standard" | "premium";
  input: { label: string; assumed: boolean };
  enclosure?: PanelEnclosure | null;  // нет — корпус по месту (старый .epd)
  devices: PanelDevice[];
  groups: Record<string, PanelGroup>;
  totals: { installed: number; demand: number; calculated: number; current: number; modules: number };
  warnings: { severity: string; text: string; group: string | null }[];
  texts: { title: string; grid: string; reserve: string };
  // to — куда приходит LOAD (автомат выхода QS3 или сразу переключатель), switch — АВР KM1
  // или переключатель SA1: с QS3 — в его вход II
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
  estimate?: SideTable;  // смета — на странице проводки (вкладка «Смета», side.estimate_side_table)
  elevations?: Elevation[];
  legend?: LegendEntry[];  // условные обозначения — плашкой на чертеже (widgets/Legend)
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
// Водорозетка или выпуск на стене: key — прибор (fixture:<id>), name — прибор словами
export interface ElevWater {
  fixture: string; key: string; name: string; n: number; kind: PipeKind;
  x: number; y: number; d: number; assumed: boolean;
}

export interface ElevWall {
  key: string;            // elevation:<комната>.<стена>
  length: number;
  openings: { kind: string; x0: number; x1: number; y0: number; y1: number; assumed: boolean }[];
  chases: { x: number; y0: number; y1: number; wide: boolean; low: boolean }[];
  boxes: ElevBox[];
  points: ElevPoint[];
  board?: { key: string; name: string; x: number; y: number; width: number; height: number };
  // Водорозетки и выпуски сантехники: n — номер прибора на листе «Сантехника»
  water?: ElevWater[];
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
