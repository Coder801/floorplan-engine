import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { feedbackItem, feedbackPage } from "@/shared/testData";
import type { FeedbackItem } from "@/shared/types";
import { Feedback } from "./Feedback";

const LIST = "GET /api/admin/feedback?status=new&offset=0&limit=50";

describe("Feedback", () => {
  it("shows the messages with counts, author, project, context and screenshots", async () => {
    const user = userEvent.setup();
    stubApi({
      [LIST]: feedbackPage([feedbackItem({
        project: { key: "p1", name: "Нагорная" }, photos: ["/shot1.png"],
        context: { sheet: "plan", version: "0.10.0", user_agent: "Firefox" },
      })], { counts: { new: 1, seen: 2, done: 3 } }),
    });
    render(<Feedback onChanged={vi.fn()} />);
    expect(await screen.findByText("Не открывается лист")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "все 6" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "новый 1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Нагорная" })).toHaveAttribute("href", "#/projects/p1");
    expect(screen.getByText("лист: plan · версия: 0.10.0")).toHaveAttribute("title", "Firefox");
    await user.click(screen.getByRole("button", { name: "Скриншот 1" }));
    expect(screen.getByRole("dialog", { name: "Скриншот" })).toContainElement(screen.getByRole("img", { name: "Скриншот" }));
  });

  it("moves the status in one click and the note by a button, counting the change up", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const sent = stubApi({
      [LIST]: feedbackPage([feedbackItem()]),
      "PATCH /api/admin/feedback/f1": (body: unknown) => feedbackItem({ ...(body as Partial<FeedbackItem>) }),
    });
    render(<Feedback onChanged={onChanged} />);
    const card = (await screen.findByText("Не открывается лист")).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "→ просмотрен" }));
    expect(sent.at(-1)).toMatchObject({ method: "PATCH", body: { status: "seen" } });
    expect(await within(card).findByRole("button", { name: "→ сделано" })).toBeInTheDocument();
    // the item stays in the "new" list; the counts move with it
    expect(screen.getByRole("button", { name: "просмотрен 1" })).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledOnce();

    expect(within(card).getByRole("button", { name: "Сохранить" })).toBeDisabled();
    await user.type(within(card).getByPlaceholderText("Заметка для себя"), "починено в 0.10");
    await user.click(within(card).getByRole("button", { name: "Сохранить" }));
    expect(sent.at(-1)).toMatchObject({ method: "PATCH", body: { admin_note: "починено в 0.10" } });
  });

  it("saves the note by Enter and shows a refusal on the card", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [LIST]: feedbackPage([feedbackItem()]), "PATCH /api/admin/feedback/f1": fail(409, "отзыв удалён") });
    render(<Feedback onChanged={vi.fn()} />);
    await user.type(await screen.findByPlaceholderText("Заметка для себя"), "ок{Enter}");
    expect(sent.at(-1)).toMatchObject({ method: "PATCH", body: { admin_note: "ок" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("отзыв удалён");
  });

  it("filters by status and kind; says when there is nothing", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [LIST]: feedbackPage([feedbackItem()]),
      "GET /api/admin/feedback?offset=0&limit=50": feedbackPage([feedbackItem()]),
      "GET /api/admin/feedback?kind=idea&offset=0&limit=50": feedbackPage([], { counts: { new: 1, seen: 0, done: 0 } }),
    });
    render(<Feedback onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: /^все/ }));
    expect(sent.at(-1)?.path).toBe("/api/admin/feedback?offset=0&limit=50");
    await user.selectOptions(screen.getByRole("combobox"), "идея");
    expect(await screen.findByText("Отзывов нет")).toBeInTheDocument();
  });

  it("pages through more than 50", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [LIST]: feedbackPage([feedbackItem()], { total: 120 }),
      "GET /api/admin/feedback?status=new&offset=50&limit=50": feedbackPage([feedbackItem({ id: "f2", text: "Второй" })], { total: 120 }),
    });
    render(<Feedback onChanged={vi.fn()} />);
    expect(await screen.findByText("1–50 из 120")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "← Новее" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Старше →" }));
    expect(await screen.findByText("Второй")).toBeInTheDocument();
    expect(sent.at(-1)?.path).toBe("/api/admin/feedback?status=new&offset=50&limit=50");
    expect(screen.getByText("51–100 из 120")).toBeInTheDocument();
  });
});
