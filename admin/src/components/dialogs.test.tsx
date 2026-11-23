import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { userRow } from "@/shared/testData";
import { IssueForm, OneTime, PersonPicker } from "./dialogs";

const anna = userRow({ id: "u2", name: "Анна", email: "anna@example.com" });
const boris = userRow({ id: "u3", name: "Борис", email: "boris@example.com", account_type: "client" });

describe("PersonPicker", () => {
  it("searches people as you type and passes the picked one with the role", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "GET /api/admin/users?q=": [anna, boris], "GET /api/admin/users?q=%D0%B0%D0%BD": [anna] });
    const onPick = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<PersonPicker title="Сотрудник" roles={["designer", "installer"]} onPick={onPick} onClose={onClose} />);
    expect(await screen.findByRole("button", { name: /Борис/ })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Имя, почта или телефон"), "ан");
    await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Борис/ })).toBeNull());
    expect(sent.at(-1)?.path).toBe("/api/admin/users?q=%D0%B0%D0%BD");
    const add = screen.getByRole("button", { name: "Добавить" });
    expect(add).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Анна/ }));
    await user.click(screen.getByRole("button", { name: "монтажник" }));
    await user.click(add);
    expect(onPick).toHaveBeenCalledWith(anna, "installer", "");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("greys out who cannot be picked and says why", async () => {
    stubApi({ "GET /api/admin/users?q=": [anna, boris] });
    render(<PersonPicker title="Сотрудник" roles={["designer"]} onPick={vi.fn()} onClose={vi.fn()}
      unfit={(u) => (u.account_type === "client" ? "хозяин квартиры" : null)} />);
    expect(await screen.findByRole("button", { name: /Борис.*— хозяин квартиры/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Анна/ })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "проектировщик" })).toBeNull();
  });

  it("says when nobody is found and offers an invite", async () => {
    const user = userEvent.setup();
    stubApi({ "GET /api/admin/users?q=": [] });
    const onInvite = vi.fn();
    render(<PersonPicker title="Участник" roles={["client"]} onPick={vi.fn()} onClose={vi.fn()} onInvite={onInvite} />);
    expect(await screen.findByText("Никого не нашлось")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Нет в списке? Ссылка-приглашение" }));
    expect(onInvite).toHaveBeenCalledOnce();
  });

  it("with an extra field waits for it and keeps the server's refusal in the dialog", async () => {
    const user = userEvent.setup();
    stubApi({ "GET /api/admin/users?q=": [anna] });
    const onPick = vi.fn().mockRejectedValue(new Error("у этого проекта уже есть поддержка"));
    const onClose = vi.fn();
    render(<PersonPicker title="Поддержка" roles={["support"]} onPick={onPick} onClose={onClose}
      extra={{ label: "Причина", placeholder: "Причина: что чинить" }} />);
    await user.click(await screen.findByRole("button", { name: /Анна/ }));
    const add = screen.getByRole("button", { name: "Добавить" });
    expect(add).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Причина" }), "  ");
    expect(add).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Причина" }), "лист");
    await user.click(add);
    expect(onPick).toHaveBeenCalledWith(anna, "support", "  лист");
    expect(await screen.findByRole("alert")).toHaveTextContent("у этого проекта уже есть поддержка");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("Отмена closes without a pick", async () => {
    stubApi({ "GET /api/admin/users?q=": fail(500, "сбой") });
    const onClose = vi.fn();
    render(<PersonPicker title="Сотрудник" roles={["designer"]} onPick={vi.fn()} onClose={onClose} />);
    expect(await screen.findByText("Никого не нашлось")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("OneTime", () => {
  it("shows the value once and copies it", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<OneTime title="Код доступа" value="K7Q-2MX" onClose={onClose} />);
    expect(screen.getByRole("dialog", { name: "Код доступа" })).toHaveTextContent("K7Q-2MX");
    expect(screen.getByText(/в списке кодов/)).toBeInTheDocument();  // a code stays in the list
    await user.click(screen.getByRole("button", { name: "Скопировать" }));
    expect(await screen.findByRole("button", { name: "Скопировано" })).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe("K7Q-2MX");
    await user.click(screen.getByRole("button", { name: "Скопировал, закрыть" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("IssueForm", () => {
  it("issues with the chosen role, the trimmed text and the term, and passes the value on", async () => {
    const user = userEvent.setup();
    const onIssue = vi.fn().mockResolvedValue("https://shtroba.app/i/abc");
    const onClose = vi.fn();
    render(<IssueForm title="Приглашение" roles={["client", "installer"]} textLabel="Почта" days={7} onIssue={onIssue} onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "монтажник" }));
    await user.type(screen.getByPlaceholderText("Почта"), " a@b.c ");
    const term = screen.getByRole("spinbutton", { name: /Срок, дней/ });
    expect(term).toHaveValue(7);
    await user.clear(term);
    await user.type(term, "3");
    await user.click(screen.getByRole("button", { name: "Выдать" }));
    expect(onIssue).toHaveBeenCalledWith("installer", "a@b.c", 3);
    expect(onClose).toHaveBeenCalledWith("https://shtroba.app/i/abc");
  });

  it("without roles issues with an empty role; a refusal stays, Отмена closes with nothing", async () => {
    const user = userEvent.setup();
    const onIssue = vi.fn().mockRejectedValue(new Error("срок больше 90 дней"));
    const onClose = vi.fn();
    render(<IssueForm title="Код" textLabel="Кому" days={30} onIssue={onIssue} onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Выдать" }));
    expect(onIssue).toHaveBeenCalledWith("", "", 30);
    expect(await screen.findByRole("alert")).toHaveTextContent("срок больше 90 дней");
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onClose).toHaveBeenCalledWith(null);
  });
});
