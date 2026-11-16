import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { QuestionsMemory } from "@/shared/questions";
import { stubApi, text } from "@/shared/testApi";
import { project, question } from "@/shared/testData";
import type { DrawerTab } from "@/shared/consts";
import type { Project } from "@/shared/types";
import { Drawer } from "./index";

function open(tab: DrawerTab, p: Project, over: Partial<Parameters<typeof Drawer>[0]> = {}) {
  const props = {
    tab, project: p, shownSource: null, onSource: vi.fn(), busy: false,
    onAnswer: vi.fn(), onReview: vi.fn(), stages: ["plan"], onShow: vi.fn(),
    memory: { current: { drafts: {} } as QuestionsMemory }, closing: false, onClose: vi.fn(), onClosed: vi.fn(), ...over,
  };
  return { ...props, ...render(<Drawer {...props} />) };
}

describe("Drawer", () => {
  it("the questions tab holds the project questions; Esc and the arrow close it", async () => {
    const { onClose, onClosed, rerender, ...props } = open("questions", project({ report: { questions: [question()], issues: [] } }));
    expect(screen.getByRole("dialog", { name: "Вопросы" })).toBeInTheDocument();
    expect(screen.getByText("Какая высота потолка?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
    rerender(<Drawer {...props} onClose={onClose} onClosed={onClosed} closing />);
    // jsdom has no AnimationEvent but has WebkitAnimation styles: React listens to the prefixed event
    fireEvent(screen.getByRole("dialog"), new Event("webkitAnimationEnd", { bubbles: true }));
    expect(onClosed).toHaveBeenCalledOnce();
  });

  it("sources: what was parsed from each file, a missing one, and show / open", async () => {
    const { onSource } = open("sources", project({
      sources: ["plan.pdf", "notes.txt"], parsed: [{ file: "plan.pdf", note: "размеры стен" }, { file: "gone.jpg", note: "" }],
    }), { shownSource: "plan.pdf" });
    expect(screen.getByText("Разобрано 2 из 3. Отметки — из intake.yaml (sources).")).toBeInTheDocument();
    const plan = screen.getByText("plan.pdf").parentElement!;
    expect(plan).toHaveTextContent("использован в разборе");
    expect(plan).toHaveTextContent("размеры стен");
    expect(within(plan).getByRole("link", { name: "Открыть в новой вкладке" })).toHaveAttribute("href", "/api/projects/p1/source/plan.pdf");
    expect(screen.getByText("notes.txt").parentElement).toHaveTextContent("не использован");
    const gone = screen.getByText("gone.jpg").parentElement!;
    expect(gone).toHaveTextContent("нет файла в source/");
    expect(within(gone).queryByRole("button")).toBeNull();
    await userEvent.click(within(plan).getByRole("button", { name: "Показать" }));
    expect(onSource).toHaveBeenCalledWith("plan.pdf");
  });

  it("sources: an old viewer and no files", () => {
    const { unmount } = open("sources", project({ sources: ["a.png"] }));
    expect(screen.getByText(/Сервер просмотра устарел/)).toBeInTheDocument();
    expect(screen.getByText("разбор неизвестен", { exact: false })).toBeInTheDocument();
    unmount();
    open("sources", project());
    expect(screen.getByText("В source/ нет файлов")).toBeInTheDocument();
  });

  it("the project tab: stages, check remarks, results and the model files", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      "GET /api/projects/p1/model/room.yaml": text("walls: []"),
      "GET /api/projects/p1/model/electrical.yaml": text("points: []"),
    });
    open("project", project({
      stages: [{ stage: "plan", status: "ready" }],
      report: { questions: [], issues: [{ severity: "error", file: "room.yaml", path: "walls.w2", message: "Контур не замкнут" }] },
      files: ["project.dxf", "estimate.md"], model: ["room.yaml", "electrical.yaml"],
    }));
    expect(screen.getByRole("heading", { name: "Квартира 42" })).toBeInTheDocument();
    expect(screen.getByText("строится")).toBeInTheDocument();
    expect(screen.getByText("Замечания проверки · 1")).toBeInTheDocument();
    expect(screen.getByText("ошибка")).toBeInTheDocument();
    expect(screen.getByText("room.yaml: walls.w2")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "project.dxf" })).toHaveAttribute("download", "project.dxf");
    expect(screen.getByRole("link", { name: "estimate.md" })).not.toHaveAttribute("download");
    expect(await screen.findByText("walls: []")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "electrical.yaml" }));
    expect(await screen.findByText("points: []")).toBeInTheDocument();
    expect(sent.map((r) => r.path)).toEqual(["/api/projects/p1/model/room.yaml", "/api/projects/p1/model/electrical.yaml"]);
  });

  it("the project tab of an unbuilt project", () => {
    open("project", project({ built: null, stages: [] }));
    expect(screen.getByText(/projects\/kv42/).parentElement).toHaveTextContent("· не собран");
    expect(screen.getByText("Замечаний нет")).toBeInTheDocument();
    expect(screen.getByText("Пока ничего не собрано")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Модель" })).toBeNull();
  });
});
