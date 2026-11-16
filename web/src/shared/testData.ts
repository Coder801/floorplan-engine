// Synthetic API answers for component tests: each factory gives a full record, a test overrides
// only the fields it is about (testApi.ts serves them).
import type { Me, User } from "./auth";
import type { Elevation, Item, Overview, OverviewReserve, Page, PricePage, PriceRow, Project, ProjectSummary, Question, Variants, VariantSummary } from "./types";

export const summary = (over: Partial<ProjectSummary> = {}): ProjectSummary => ({
  id: "p1", name: "kv42", title: "Квартира 42", built: 1_763_200_000, stale: false,
  stages: [{ stage: "plan", status: "ok" }, { stage: "electrical", status: "ok" }],
  open_questions: 0, waiting_answers: 0, preview: false, ...over,
});

export const project = (over: Partial<Project> = {}): Project => ({
  ...summary(),
  can: { choose_variant: true, answer: true, review: true },
  report: { questions: [], issues: [] }, answers: {}, artifact: true, dxf: null, files: [], sources: [], model: [],
  ...over,
});

export const question = (over: Partial<Question> = {}): Question => ({
  id: "q1", stage: "plan", severity: "major", state: "open", text: "Какая высота потолка?", answer: "value",
  assumption: 2700, unit: "mm", target: "room.yaml: ceiling_height", ...over,
});

export const user = (over: Partial<User> = {}): User => ({
  id: "u1", name: "Иван", email: "ivan@example.com", phone: null, account_type: "pro", superuser: false,
  space: { kind: "studio", name: "Ампер", business: "electric", city: "Киев" }, ...over,
});

export const me = (over: Partial<Me> = {}): Me => ({ auth: true, user: user(), ...over });

export const priceRow = (over: Partial<PriceRow> = {}): PriceRow => ({
  key: "work.socket", section: "rough", unit: "шт", name: { ru: "Установка подрозетника", uk: "Встановлення підрозетника" },
  hint: null, price: 100, service: null,
  market: { n: 3, min: 80, q1: 90, median: 120, q3: 140, max: 200, basis: "бетон",
            quotes: [{ source: "s1", price: 80, text: "подрозетник в бетоне" }] },
  ...over,
});

export const pricePage = (over: Partial<PricePage> = {}): PricePage => ({
  file: "prices.yaml", exists: true, currency: "грн", date: "2026-11-01", note: "", rows: [priceRow()],
  market: {
    region: "Киев", collected: "2026-10-20", currency: "грн",
    period: { start: "2026-01", end: "2026-10", dated: 1, undated: 0 },
    sources: [{ id: "s1", name: "Мастер Сервис", url: "https://example.com/prices", date: "2026-10-01", kind: "company", note: "" }],
  },
  issues: [], editable: true, ...over,
});

export const item = (l: string, over: Partial<Item> = {}): Item => ({ k: "s", c: "#202020", l, d: "M10 10L50 50", ...over });

export const page = (over: Partial<Page> = {}): Page => ({
  name: "План", format: "A3", size: [420, 297], background: "#ffffff", stage: "plan",
  items: [item("A-WALL"), item("E-SOCKET", { o: "point:s1" })], ...over,
});

export const overview = (over: Partial<Overview> = {}): Overview => ({
  object: { name: "Квартира 42", object: "Квартира", building: "ул. Нагорная, 16", code: "КВ-42", stage: "Р", organization: "" },
  language: "ru",
  rooms: [{ id: "r1", name: "Кухня", area: 12.5, wet: true }, { id: "r2", name: "Спальня", area: 15, wet: false }],
  area: 27.5, ceiling: { height: 2700, assumed: true }, ...over,
});

export const variantSummary = (over: Partial<VariantSummary> = {}): VariantSummary => ({
  key: "standard-ceiling-boxes", mode: "standard", route: "ceiling", distribution: "boxes", total: 50000, material: 30000, work: 20000,
  currency: "грн", unpriced: 0, cable_m: 320, devices: 18, chases_m: 60, conduit_m: 0, edited: false, ...over,
});

// The saved set and its neighbours: the floor route and the loop distribution
export const variants = (over: Partial<Variants> = {}): Variants => ({
  active: "standard-ceiling-boxes", default: "standard-ceiling-boxes",
  items: [
    variantSummary(),
    variantSummary({ key: "standard-floor-boxes", route: "floor", total: 47000, cable_m: 280 }),
    variantSummary({ key: "standard-ceiling-loop", distribution: "loop", total: 52000 }),
  ],
  ...over,
});

export const reserve = (over: Partial<OverviewReserve> = {}): OverviewReserve => ({
  limit_kw: 3, limit_assumed: false,
  items: [
    { id: "QF1", purpose: "Свет", power: 400, kind: "light", on: true },
    { id: "QF2", purpose: "Розетки кухни", power: 2000, steady: 300, peak: 1500, kind: "sockets", on: false },
    { id: "QF3", purpose: "Духовка", power: 3500, steady: 0, peak: 3500, kind: "heavy", on: false },
  ],
  ...over,
});

export const elevation = (over: Partial<Elevation> = {}): Elevation => ({
  key: "elevation:kitchen.w1", title: "Кухня · стена 1", behind: "коридор", length: 3600, height: 2700, height_assumed: true, top: 2700,
  openings: [], chases: [], boxes: [], back: [],
  points: [{ id: "p1", key: "point:p1", n: 3, type: "socket", name: "Розетка", x: 400, y: 300, posts: 1, group: "QF4", color: "#123456", from: "К1" }],
  water: [{ fixture: "s", key: "fixture:s", name: "Мойка", n: 2, kind: "cold", x: 1000, y: 550, d: 16, assumed: false }],
  ...over,
});
