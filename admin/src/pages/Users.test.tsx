import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { projectRow, studioRow, userDetail, userRow } from "@/shared/testData";
import { UserList, UserView } from "./Users";

const DETAIL = "GET /api/admin/users/u1";

describe("UserList", () => {
  it("searches on the server after typing stops and filters by account type", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      "GET /api/admin/users?q=": [
        userRow({ space: { ...studioRow() } }),
        userRow({ id: "u2", name: "Ольга", account_type: "client", active: false }),
        userRow({ id: "u3", name: "Новичок", account_type: null }),
      ],
      "GET /api/admin/users?q=%D0%BE%D0%BB": [userRow({ id: "u2", name: "Ольга", account_type: "client" })],
    });
    render(<UserList id={null} version={0} />);
    expect(await screen.findByRole("link", { name: /Иван Петров/ })).toHaveTextContent("ivan@example.com · «Ампер»");
    expect(screen.getByRole("link", { name: /Ольга/ })).toHaveTextContent("заблокирован");
    await user.selectOptions(screen.getByRole("combobox"), "не выбрана");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("link", { name: /Новичок/ })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox"), "Все учётки");
    await user.type(screen.getByPlaceholderText("Имя, почта или телефон"), "ол");
    await vi.waitFor(() => expect(screen.getAllByRole("link")).toHaveLength(1));
    expect(sent.at(-1)?.path).toBe("/api/admin/users?q=%D0%BE%D0%BB");
  });
});

describe("UserView", () => {
  it("shows the person with the workspace, projects, login methods and sessions", async () => {
    stubApi({
      [DETAIL]: userDetail({
        superuser: true,
        space: { ...studioRow(), role: "owner" },
        projects: [{ ...projectRow(), role: "client" }],
        providers: ["google", "email"],
        sessions: [{ id: "x", agent: "Firefox", created: null, seen: null }],
      }),
    });
    render(<UserView id="u1" me="u9" onChanged={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Иван Петров" })).toBeInTheDocument();
    expect(screen.getByText("владелец платформы")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "«Ампер»" })).toHaveAttribute("href", "#/studios/s1");
    expect(screen.getByRole("link", { name: "nahirna-16" })).toHaveAttribute("href", "#/projects/p1");
    expect(screen.getByText("google, email")).toBeInTheDocument();
    expect(screen.getByText("Firefox")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "журнал" })).toHaveAttribute("href", "#/events?user=u1");
  });

  it("your own record cannot be blocked; no sessions — nothing to end", async () => {
    stubApi({ [DETAIL]: userDetail() });
    render(<UserView id="u1" me="u1" onChanged={vi.fn()} />);
    expect(await screen.findByText("· это вы")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Заблокировать" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Завершить сеансы" })).toBeDisabled();
    expect(screen.getByText("Нет действующих")).toBeInTheDocument();
  });

  it("blocks after a confirmation, then unblocks", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const sent = stubApi({
      [DETAIL]: userDetail(),
      "POST /api/admin/users/u1/active": (body: unknown) => userDetail({ active: (body as { active: boolean }).active }),
    });
    render(<UserView id="u1" me="u9" onChanged={onChanged} />);
    await user.click(await screen.findByRole("button", { name: "Заблокировать" }));
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(sent.at(-1)?.body).toEqual({ active: false });
    await user.click(await screen.findByRole("button", { name: "Разблокировать" }));
    expect(sent.at(-1)?.body).toEqual({ active: true });
    expect(await screen.findByRole("button", { name: "Заблокировать" })).toBeEnabled();
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("ends all sessions and shows a refusal", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [DETAIL]: userDetail({ sessions: [{ id: "x", agent: "", created: null, seen: null }] }),
      "POST /api/admin/users/u1/logout": fail(409, "сеанс уже завершён"),
    });
    render(<UserView id="u1" me="u9" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Завершить сеансы" }));
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(sent.at(-1)?.path).toBe("/api/admin/users/u1/logout");
    expect(await screen.findByRole("alert")).toHaveTextContent("сеанс уже завершён");
  });

  it("shows a load error", async () => {
    stubApi({ [DETAIL]: fail(404, "нет такого человека") });
    render(<UserView id="u1" me="u9" onChanged={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет такого человека");
  });
});
