import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { invite, person, projectRow, studioDetail, studioRow, userRow } from "@/shared/testData";
import { StudioList, StudioView } from "./Studios";

const ivan = person({ id: "u1", name: "Иван" });
const DETAIL = "GET /api/admin/studios/s1";

describe("StudioList", () => {
  it("lists studios and filters by name and kind", async () => {
    const user = userEvent.setup();
    stubApi({
      "GET /api/admin/studios": [
        studioRow({ city: "Киев" }),
        studioRow({ id: "s2", name: "Ремонт Ольги", kind: "personal", members: 1, projects: 2 }),
      ],
    });
    render(<StudioList id={null} version={0} />);
    expect(await screen.findByRole("link", { name: /Ампер/ })).toHaveTextContent("2 уч. · 1 пр. · Киев");
    await user.selectOptions(screen.getByRole("combobox"), "Мой ремонт");
    expect(screen.queryByRole("link", { name: /Ампер/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Ремонт Ольги/ })).toHaveAttribute("href", "#/studios/s2");
    await user.type(screen.getByPlaceholderText("Название"), "ампер");
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("StudioView", () => {
  it("a firm changes a member's role at once and tells the list", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const sent = stubApi({
      [DETAIL]: studioDetail({ members: [{ user: ivan, role: "designer", since: null }], projects: [projectRow()] }),
      "PATCH /api/admin/studios/s1/members/u1": studioDetail({ members: [{ user: ivan, role: "installer", since: null }] }),
    });
    render(<StudioView id="s1" onChanged={onChanged} />);
    expect(await screen.findByRole("heading", { name: "Ампер" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "nahirna-16" })).toHaveAttribute("href", "#/projects/p1");
    await user.selectOptions(screen.getByRole("combobox"), "монтажник");
    expect(sent.at(-1)).toMatchObject({ method: "PATCH", body: { role: "installer" } });
    expect(onChanged).toHaveBeenCalledOnce();
    expect(screen.getByRole("combobox")).toHaveValue("installer");
  });

  it("shows why the last owner cannot be removed", async () => {
    const user = userEvent.setup();
    stubApi({
      [DETAIL]: studioDetail({ members: [{ user: ivan, role: "owner", since: null }] }),
      "DELETE /api/admin/studios/s1/members/u1": fail(409, "у студии остаётся владелец"),
    });
    render(<StudioView id="s1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Убрать" }));
    expect(screen.getByText("Убрать Иван?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("у студии остаётся владелец");
  });

  it("«Мой ремонт» has no employees: no buttons, a reason, the role as a word", async () => {
    stubApi({ [DETAIL]: studioDetail({ kind: "personal", members: [{ user: ivan, role: "owner", since: null }] }) });
    render(<StudioView id="s1" onChanged={vi.fn()} />);
    expect(await screen.findByText("В «Моём ремонте» только владелец.")).toBeInTheDocument();
    expect(screen.getByText("владелец")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Добавить" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Убрать" })).toBeNull();
    expect(screen.getByText("Проектов нет")).toBeInTheDocument();
  });

  it("projects without an owner say so", async () => {
    stubApi({ [DETAIL]: studioDetail({ kind: "unowned", folder: "" }) });
    render(<StudioView id="s1" onChanged={vi.fn()} />);
    expect(await screen.findByText("У проектов без владельца участников нет.")).toBeInTheDocument();
    expect(screen.getByText("корень")).toBeInTheDocument();
  });

  it("adds an employee: a client account and someone else's employee cannot be picked", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [DETAIL]: studioDetail(),
      "GET /api/admin/users?q=": [
        userRow({ id: "u2", name: "Клиент", account_type: "client" }),
        userRow({ id: "u3", name: "Чужой", space: { ...studioRow({ id: "s9", name: "Вольт" }) } }),
        userRow({ id: "u4", name: "Свободный" }),
      ],
      "POST /api/admin/studios/s1/members": studioDetail({ members: [{ user: person({ id: "u4", name: "Свободный" }), role: "designer", since: null }] }),
    });
    render(<StudioView id="s1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Добавить" }));
    expect(await screen.findByRole("button", { name: /Клиент.*— хозяин квартиры/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Чужой.*уже в «Вольт»/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Свободный/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Добавить" }));
    expect(sent.at(-1)?.body).toEqual({ user: "u4", role: "owner" });
    expect(await screen.findByText("Участники (1)")).toBeInTheDocument();
  });

  it("issues an invite link, shows it once and revokes an active invite", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [DETAIL]: studioDetail({ invites: [invite({ role: "designer" })] }),
      "POST /api/admin/studios/s1/invites": { url: "https://shtroba.app/i/st" },
      "DELETE /api/admin/invites/i1": { ok: true },
    });
    render(<StudioView id="s1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Ссылка" }));
    await user.type(screen.getByPlaceholderText("Почта (для списка)"), "new@example.com");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Выдать" }));
    expect(sent.find((r) => r.method === "POST")?.body).toEqual({ role: "designer", email: "new@example.com", days: 7 });
    expect(await screen.findByRole("dialog", { name: "Ссылка-приглашение" })).toHaveTextContent("https://shtroba.app/i/st");
    await user.click(screen.getByRole("button", { name: "Скопировал, закрыть" }));
    await user.click(screen.getByRole("button", { name: "Отозвать" }));
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(sent.at(-2)).toMatchObject({ method: "DELETE", path: "/api/admin/invites/i1" });
  });
});
