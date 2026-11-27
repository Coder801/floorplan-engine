import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReportDialog } from "./index";

describe("ReportDialog", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("all parts and portrait by default; Открыть opens the report in a new tab and closes", async () => {
    const user = userEvent.setup();
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const onClose = vi.fn();
    render(<ReportDialog projectKey="кв 42" onClose={onClose} />);
    expect(screen.getByRole("dialog", { name: "Смета для печати" })).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Электрика" });
    expect(group.querySelectorAll("input:checked")).toHaveLength(6);
    expect(screen.getByRole("radio", { name: "Книжная" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("checkbox", { name: "План электрики" }));
    await user.click(screen.getByRole("radio", { name: "Альбомная" }));
    await user.click(screen.getByRole("button", { name: "Открыть" }));
    expect(open).toHaveBeenCalledWith(
      `/api/projects/${encodeURIComponent("кв 42")}/result?parts=material_rough,material_finish,work_rough,work_finish,panel&orientation=landscape`,
      "_blank", "noopener");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Скачать PDF fetches the PDF of the same choice, saves it under the server's name and closes", async () => {
    const user = userEvent.setup();
    const name = "Кв 42 — Однолинейная схема щита.pdf";
    const fetch = vi.fn().mockResolvedValue(new Response(new Blob(["%PDF-1.7"]), {
      status: 200,
      headers: { "Content-Disposition": `attachment; filename="report.pdf"; filename*=UTF-8''${encodeURIComponent(name)}` },
    }));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:pdf"), revokeObjectURL: vi.fn() }));
    const saved: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    const onClose = vi.fn();
    render(<ReportDialog projectKey="p1" onClose={onClose} />);
    for (const n of ["План электрики", "Черновые материалы", "Чистовые материалы", "Черновые работы", "Чистовые работы"]) {
      await user.click(screen.getByRole("checkbox", { name: n }));
    }
    await user.click(screen.getByRole("button", { name: "Скачать PDF" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/result.pdf?parts=panel&orientation=portrait");
    expect(saved).toEqual([name]);
    click.mockRestore();
  });

  it("a refused PDF keeps the dialog open with the server's reason", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "PDF-сервис не настроен: задайте SHTROBA_PDF_URL" }), { status: 503 })));
    const onClose = vi.fn();
    render(<ReportDialog projectKey="p1" onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Скачать PDF" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось сделать PDF: PDF-сервис не настроен");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Скачать PDF" })).toBeEnabled();
  });

  it("nothing ticked: Открыть is off; the last choice comes back", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("open", vi.fn());
    const { unmount } = render(<ReportDialog projectKey="p1" onClose={vi.fn()} />);
    for (const name of ["План электрики", "Черновые материалы", "Чистовые материалы", "Черновые работы", "Однолинейная схема щита"]) {
      await user.click(screen.getByRole("checkbox", { name }));
    }
    await user.click(screen.getByRole("button", { name: "Открыть" }));
    unmount();
    render(<ReportDialog projectKey="p1" onClose={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: "Чистовые работы" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "План электрики" })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Чистовые работы" }));
    expect(screen.getByRole("button", { name: "Открыть" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Скачать PDF" })).toBeDisabled();
  });

  it("Отмена and Esc close", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<ReportDialog projectKey="p1" onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("Excel: only the estimate sections, fetches result.xlsx of the choice and saves it", async () => {
    const user = userEvent.setup();
    const name = "Кв 42 — Смета электрики.xlsx";
    const fetch = vi.fn().mockResolvedValue(new Response(new Blob(["PK"]), {
      status: 200,
      headers: { "Content-Disposition": `attachment; filename="estimate.xlsx"; filename*=UTF-8''${encodeURIComponent(name)}` },
    }));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    const saved: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download);
    });
    const onClose = vi.fn();
    render(<ReportDialog projectKey="p1" format="xlsx" onClose={onClose} />);
    expect(screen.queryByRole("radio", { name: "Книжная" })).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "Чистовые материалы" }));
    await user.click(screen.getByRole("button", { name: "Скачать Excel" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/result.xlsx?parts=material_rough,work_rough,work_finish");
    expect(saved).toEqual([name]);
    click.mockRestore();
  });
});
