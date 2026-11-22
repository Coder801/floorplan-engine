import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetSelection, view } from "@/shared/store";
import { fail, stubApi } from "@/shared/testApi";
import { overview, page, pricePage, project, question, summary, variants } from "@/shared/testData";
import type { ManifestPage, Page, SideTable } from "@/shared/types";
import { FORMAT_VERSION } from "@/shared/version";
import { Viewer, unresolved } from "./index";

// The drawing areas draw in canvas and WebGL (engine/): jsdom has neither, so the page is tested
// with stand-ins that only say which page they got. The engines are tested on their own
vi.mock("@/widgets/SheetStage", () => ({
  LIGHT_MODES: ["wiring", "links"],
  SheetStage: ({ page: pg }: { page: Page }) => <div data-testid="drawing">Чертёж: {pg.name}</div>,
}));
vi.mock("@/widgets/PanelStage", () => ({ PanelStage: ({ page: pg }: { page: Page }) => <div data-testid="drawing">Щит: {pg.name}</div> }));
vi.mock("@/widgets/ElevationStage", () => ({ ElevationStage: () => <div data-testid="drawing">Развёртка</div> }));
vi.mock("@/widgets/WallMap", () => ({ WallMap: () => null }));

const P = "/api/projects/p1";
const sheets: ManifestPage[] = [
  { index: 0, name: "План", format: "A3", size: [420, 297], file: "01-plan", stage: "plan" },
  { index: 1, name: "Проводка", format: "A3", size: [420, 297], file: "04-wiring", stage: "wiring" },
];
const estimate: SideTable = {
  title: "Смета электрики", columns: ["№", "Позиция", "Сумма"], align: ["left", "left", "right"],
  rows: [{ cells: ["1", "Штроба", "100"] }], total: ["", "Итого", "100"],
};
const manifest = (over = {}) => ({ version: FORMAT_VERSION, pages: sheets, overview: overview(), variants: variants(), ...over });

// A built project with one question and its two sheets
function serve(routes: Record<string, unknown> = {}) {
  return stubApi({
    "GET /api/projects": [summary(), summary({ id: "p2", name: "dacha", title: "Дача" })],
    [`GET ${P}`]: project({ report: { questions: [question()], issues: [] }, files: ["estimate.xlsx"] }),
    [`GET ${P}/sheets`]: manifest(),
    [`GET ${P}/sheets/0`]: page({ name: "План" }),
    [`GET ${P}/sheets/1`]: page({ name: "Проводка", stage: "wiring", estimate }),
    ...routes,
  });
}

const go = (hash: string) => act(() => { location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); });

beforeEach(() => {
  resetSelection();
  view.set({ hidden: new Set(), extra: new Set(), filter3d: { groups: null, room: null } });
  localStorage.setItem("notice:alpha", "seen");  // the stage notice is tested on its own
});

describe("Viewer", () => {
  it("without a project it lists the projects; a card opens one on its overview", async () => {
    serve();
    render(<Viewer />);
    const welcome = await screen.findByRole("dialog", { name: /Shtroba/ });
    await userEvent.click(within(welcome).getByRole("button", { name: /Квартира 42/ }));
    expect(location.hash).toBe("#p1");
    await go("#p1");
    expect(await screen.findByRole("heading", { level: 1, name: "Общие сведения" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Квартира 42/ })).toBeInTheDocument();  // the project switch in the header
    expect(document.title).toMatch(/^Квартира 42 · Общие сведения — Shtroba/);
  });

  it("the header tabs open the plan, the electrical section and the estimate; the place is remembered", async () => {
    const user = userEvent.setup();
    serve();
    location.hash = "#p1";
    render(<Viewer />);
    const tabs = await screen.findByRole("navigation", { name: "Листы" });
    expect(within(tabs).getByRole("button", { name: "Общие сведения" })).toHaveAttribute("aria-current", "page");
    await user.click(within(tabs).getByRole("button", { name: "План" }));
    expect(await screen.findByText("Чертёж: План")).toBeInTheDocument();
    expect(within(tabs).getByRole("button", { name: "План" })).toHaveAttribute("aria-current", "page");
    await user.click(within(tabs).getByRole("button", { name: "Электрика" }));
    expect(await screen.findByText("Чертёж: Проводка")).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("place:p1")!)).toMatchObject({ sheet: 1, info: false });
    await user.click(within(tabs).getByRole("button", { name: "Смета" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Смета электрики" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Скачать Excel" })).toHaveAttribute("href", `${P}/out/estimate.xlsx`);
  });

  it("a question is answered from the header panel and the project is read again", async () => {
    const user = userEvent.setup();
    const sent = serve({ [`POST ${P}/answers`]: { built: true, rebuilt: false } });
    location.hash = "#p1";
    render(<Viewer />);
    await user.click(await screen.findByRole("radio", { name: "Вопросы: открытых 1" }));
    const drawer = screen.getByRole("dialog", { name: "Вопросы" });
    await user.type(within(drawer).getByRole("textbox", { name: "Ваш ответ" }), "2650");
    await user.click(within(drawer).getByRole("button", { name: "Сохранить" }));
    expect(sent.find((r) => r.method === "POST")?.body).toEqual({ id: "q1", answer: 2650 });
    await waitFor(() => expect(sent.filter((r) => r.path === P)).toHaveLength(2));
  });

  it("the setup wizard opens from the overview and applies everything with one rebuild", async () => {
    const user = userEvent.setup();
    const sent = serve({ [`POST ${P}/wizard`]: { built: true, rebuilt: true } });
    location.hash = "#p1";
    render(<Viewer />);
    // The overview remounts once the sheet under it is loaded (its Boundary appears): wait for it
    await waitFor(() => expect(sent.some((r) => r.path === `${P}/sheets/0`)).toBe(true));
    await act(() => new Promise((r) => setTimeout(r, 0)));
    await user.click(screen.getAllByRole("button", { name: "Настроить проект" })[0]);
    const wizard = await screen.findByRole("dialog", { name: "Настройка проекта" });
    await user.click(within(wizard).getByRole("radio", { name: /По полу/ }));
    await user.click(within(wizard).getByRole("button", { name: "Итог" }));
    await user.click(within(wizard).getByRole("button", { name: "Пересчитать" }));
    expect(sent.find((r) => r.path === `${P}/wizard`)?.body).toMatchObject({ variant: { route: "floor" } });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Настройка проекта" })).toBeNull());
    await waitFor(() => expect(sent.filter((r) => r.path === `${P}/sheets`).length).toBeGreaterThan(1));
  });

  it("says when the sheets are of another format, or not built yet", async () => {
    serve({ [`GET ${P}/sheets`]: manifest({ version: FORMAT_VERSION + 1 }) });
    location.hash = "#p1";
    const { unmount } = render(<Viewer />);
    expect(await screen.findByRole("alert")).toHaveTextContent(`Листы в формате версии ${FORMAT_VERSION + 1}`);
    unmount();
    serve({ [`GET ${P}`]: project({ artifact: false, report: null }) });
    render(<Viewer />);
    expect(await screen.findByText("Нет out/project.epd — листы появятся после build")).toBeInTheDocument();
    expect(screen.getByText("Проект не собран: uv run floorplan-engine build projects/kv42")).toBeInTheDocument();
  });

  it("a failed project load shows the server's reason", async () => {
    serve({ [`GET ${P}`]: fail(404, "Нет такого проекта") });
    location.hash = "#p1";
    render(<Viewer />);
    expect(await screen.findByRole("alert")).toHaveTextContent("404: Нет такого проекта");
  });

  it("the project switch in the header opens the project menu", async () => {
    const user = userEvent.setup();
    serve();
    location.hash = "#p1";
    render(<Viewer />);
    await screen.findByRole("heading", { level: 1, name: "Общие сведения" });
    await user.click(screen.getByRole("button", { name: /Квартира 42/ }));
    const menu = screen.getByRole("navigation", { name: "Проекты" });
    await user.click(within(menu).getByRole("button", { name: /Дача/ }));
    expect(location.hash).toBe("#p2");
  });

  it("the studio settings open from the address and go back where they were opened", async () => {
    serve({ "GET /api/prices": pricePage() });
    location.hash = "#@studio/prices";
    render(<Viewer />);
    expect(await screen.findByRole("dialog", { name: "Настройки студии" })).toBeInTheDocument();
    expect(await screen.findByRole("textbox", { name: /Цена:/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Назад" }));
    expect(location.hash).toBe("");
  });

  it("the tasks tab of a project in the database", async () => {
    const user = userEvent.setup();
    const { workState } = await import("@/widgets/WorkStage/mock");
    serve({ [`GET ${P}`]: project({ work: true }), [`GET ${P}/work`]: workState() });
    location.hash = "#p1";
    render(<Viewer />);
    await user.click(await screen.findByRole("button", { name: "Задачи" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Работы по плану" })).toBeInTheDocument();
    await user.click(within(screen.getByRole("region", { name: "На приёмке" })).getByRole("button", { name: /Распаечные коробки/ }));
    expect(screen.getByRole("dialog", { name: "Распаечные коробки" })).toBeInTheDocument();
  });

  it("counts the unresolved questions", () => {
    expect(unresolved(null)).toBe(0);
    expect(unresolved(project({ report: { questions: [question(), question({ id: "q2", state: "answered" }), question({ id: "q3", state: "text" })], issues: [] } }))).toBe(2);
  });
});

// The client tour (widgets/Tour): only the client side, once per browser, after the stage notice
describe("Viewer: the client tour", () => {
  const client = (can = { choose_variant: true, answer: true, review: false }) =>
    project({ can, report: { questions: [question()], issues: [] } });
  // jsdom has no layout: every element gets a box, so the tour finds its anchors
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      { left: 100, top: 10, width: 120, height: 36, right: 220, bottom: 46, x: 100, y: 10, toJSON: () => ({}) } as DOMRect);
  });
  afterEach(() => vi.restoreAllMocks());

  it("starts by itself for a client on the overview; Esc closes it for good", async () => {
    const user = userEvent.setup();
    serve({ [`GET ${P}`]: client() });
    location.hash = "#p1";
    render(<Viewer />);
    expect(await screen.findByRole("dialog", { name: "Это ваш проект" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Как пользоваться" })).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Это ваш проект" })).toBeNull());
    expect(localStorage.getItem("tour:client")).toBe("seen");
    expect(screen.getByRole("button", { name: "Как пользоваться" })).toHaveAttribute("aria-pressed", "false");
  });

  it("drops the questions and setup steps without the rights", async () => {
    serve({ [`GET ${P}`]: client({ choose_variant: false, answer: false, review: false }) });
    location.hash = "#p1";
    render(<Viewer />);
    await screen.findByRole("dialog", { name: "Это ваш проект" });
    expect(screen.getByText("1 из 3")).toBeInTheDocument();
  });

  it("waits for the stage notice to close", async () => {
    const user = userEvent.setup();
    localStorage.removeItem("notice:alpha");
    const sent = serve({ [`GET ${P}`]: client() });
    location.hash = "#p1";
    render(<Viewer />);
    await waitFor(() => expect(sent.some((r) => r.path === `${P}/sheets/0`)).toBe(true));
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(screen.queryByRole("dialog", { name: "Это ваш проект" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Понятно, продолжить" }));
    expect(await screen.findByRole("dialog", { name: "Это ваш проект" })).toBeInTheDocument();
  });

  it("once seen it does not start again; «?» replays it from step 1 and closes it", async () => {
    const user = userEvent.setup();
    localStorage.setItem("tour:client", "seen");
    serve({ [`GET ${P}`]: client() });
    location.hash = "#p1";
    render(<Viewer />);
    const help = await screen.findByRole("button", { name: "Как пользоваться" });
    await screen.findByRole("heading", { level: 1, name: "Общие сведения" });
    expect(screen.queryByRole("dialog", { name: "Это ваш проект" })).toBeNull();
    await user.click(help);
    expect(screen.getByRole("dialog", { name: "Это ваш проект" })).toBeInTheDocument();
    expect(help).toHaveAttribute("aria-pressed", "true");
    await user.click(help);
    expect(screen.queryByRole("dialog", { name: "Это ваш проект" })).toBeNull();
  });

  it("the studio gets no tour and no «?»", async () => {
    serve();
    location.hash = "#p1";
    render(<Viewer />);
    await screen.findByRole("heading", { level: 1, name: "Общие сведения" });
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(screen.queryByRole("dialog", { name: "Это ваш проект" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Как пользоваться" })).toBeNull();
  });

  it("«?tour» in the address starts it for the studio too, even when seen, and leaves the address", async () => {
    localStorage.setItem("tour:client", "seen");
    window.history.replaceState(null, "", "/?tour#p1");
    serve();
    render(<Viewer />);
    expect(await screen.findByRole("dialog", { name: "Это ваш проект" })).toBeInTheDocument();
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("#p1");
  });
});
