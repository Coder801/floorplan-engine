import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { Feedback } from "./index";

const where = () => ({ path: "/#p1", width: 1280, height: 800, dpr: 2, userAgent: "Test" });
const png = (name: string) => new File(["x"], name, { type: "image/png" });

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn((f: File) => `blob:${f.name}`), revokeObjectURL: vi.fn() }));
});

describe("Feedback", () => {
  it("sends the kind, the text, the context and the screenshots, then thanks", async () => {
    const user = userEvent.setup({ applyAccept: false });  // a dropped file of another type gets through the picker
    const sent = stubApi({ "POST /api/feedback": { id: "f1" } });
    const onClose = vi.fn();
    const { container } = render(<Feedback project={{ key: "p1", title: "Квартира 42" }} sheet="plan" sheetTitle="План"
                                           onClose={onClose} where={where} />);
    expect(screen.getByRole("dialog", { name: "Оставить отзыв" })).toBeInTheDocument();
    const textArea = screen.getByRole("textbox", { name: "Сообщение" });
    expect(textArea).toHaveFocus();
    expect(screen.getByText(/проект «Квартира 42», лист «План»/)).toBeInTheDocument();
    const send = screen.getByRole("button", { name: "Отправить" });
    expect(send).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "Идея" }));
    expect(textArea).toHaveAttribute("placeholder", "Чего не хватает или что сделать удобнее?");
    await user.type(textArea, "  Тёмная тема для печати ");
    expect(screen.getByText("22 / 4000")).toBeInTheDocument();
    await user.upload(container.ownerDocument.querySelector<HTMLInputElement>("input[type=file]")!, [png("a.png"), new File(["x"], "b.gif", { type: "image/gif" })]);
    expect(screen.getByRole("img", { name: "a.png" })).toBeInTheDocument();
    expect(screen.getByText("b.gif: подходят JPEG, PNG или WebP")).toBeInTheDocument();
    await user.click(send);
    expect(await screen.findByRole("heading", { name: "Спасибо!" })).toBeInTheDocument();
    const form = sent[0].body as FormData;
    expect(form.get("kind")).toBe("idea");
    expect(form.get("text")).toBe("Тёмная тема для печати");
    expect(form.get("project")).toBe("p1");
    expect(JSON.parse(String(form.get("context")))).toMatchObject({ sheet: "plan", path: "/#p1", viewport: "1280×800@2" });
    expect(form.getAll("photos")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("a screenshot can be removed", async () => {
    const user = userEvent.setup();
    const { container } = render(<Feedback onClose={vi.fn()} where={where} />);
    expect(screen.getByText(/приложатся версия/)).toBeInTheDocument();
    await user.upload(container.ownerDocument.querySelector<HTMLInputElement>("input[type=file]")!, png("a.png"));
    await user.click(screen.getByRole("button", { name: "Убрать a.png" }));
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("says why a send failed in words; 429 keeps the server's text", async () => {
    const user = userEvent.setup();
    stubApi({ "POST /api/feedback": fail(401, "no session") });
    const first = render(<Feedback onClose={vi.fn()} where={where} />);
    await user.type(screen.getByRole("textbox", { name: "Сообщение" }), "Ошибка{Enter}");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Сессия закончилась — войдите снова и отправьте ещё раз.");
    first.unmount();

    stubApi({ "POST /api/feedback": fail(429, "Попробуйте через 5 минут") });
    render(<Feedback onClose={vi.fn()} where={where} />);
    await user.type(screen.getByRole("textbox", { name: "Сообщение" }), "Ошибка");
    await user.click(screen.getByRole("button", { name: "Отправить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Попробуйте через 5 минут");
  });

  it("a miss on the veil closes only an empty form", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Feedback onClose={onClose} where={where} />);
    const veil = screen.getByRole("dialog").parentElement!;
    await user.type(screen.getByRole("textbox", { name: "Сообщение" }), "текст");
    await user.click(veil);
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
