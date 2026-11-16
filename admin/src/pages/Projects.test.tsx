import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { invite, person, projectDetail, projectRow, userRow } from "@/shared/testData";
import { ProjectList, ProjectView } from "./Projects";

const ivan = person({ id: "u1", name: "Иван" });
const DETAIL = "GET /api/admin/projects/p1";

describe("ProjectList", () => {
  it("lists projects as links and filters by folder, name or studio", async () => {
    const user = userEvent.setup();
    stubApi({
      "GET /api/admin/projects": [
        projectRow(),
        projectRow({ id: "p2", slug: "dacha", name: "Дача", studio: { id: "s2", name: "Вольт" } }),
      ],
    });
    render(<ProjectList id="p2" version={0} />);
    expect(await screen.findByRole("link", { name: /nahirna-16/ })).toHaveAttribute("href", "#/projects/p1");
    await user.type(screen.getByPlaceholderText("Папка, название или студия"), "вольт");
    expect(screen.queryByRole("link", { name: /nahirna-16/ })).toBeNull();
    expect(screen.getByRole("link", { name: /dacha/ })).toBeInTheDocument();
  });
});

describe("ProjectView", () => {
  it("shows the project with its sections and empty states", async () => {
    stubApi({ [DETAIL]: projectDetail() });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("nahirna-16 · Квартира на Нагорной");
    expect(screen.getByRole("link", { name: "«Ампер»" })).toHaveAttribute("href", "#/studios/s1");
    expect(screen.getByRole("link", { name: "журнал" })).toHaveAttribute("href", "#/events?project=p1");
    expect(screen.getByText("Только студия проекта")).toBeInTheDocument();
    expect(screen.getByText("Кодов нет")).toBeInTheDocument();
    expect(screen.getByText("Приглашений нет")).toBeInTheDocument();
    expect(screen.getByText("Доступа поддержки нет")).toBeInTheDocument();
  });

  it("shows a load error and nothing else", async () => {
    stubApi({ [DETAIL]: fail(404, "нет такого проекта") });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет такого проекта");
  });

  it("removes a member after a confirmation and tells the list", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const sent = stubApi({
      [DETAIL]: projectDetail({ members: [{ user: ivan, role: "client", since: null }] }),
      "DELETE /api/admin/projects/p1/members/u1": projectDetail(),
    });
    render(<ProjectView id="p1" onChanged={onChanged} />);
    expect(await screen.findByText("Участники (1)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Убрать" }));
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(await screen.findByText("Участники (0)")).toBeInTheDocument();
    expect(sent.at(-1)?.method).toBe("DELETE");
    expect(onChanged).toHaveBeenCalledOnce();
  });

  it("shows the refusal of a change next to the actions", async () => {
    const user = userEvent.setup();
    stubApi({
      [DETAIL]: projectDetail({ members: [{ user: ivan, role: "client", since: null }] }),
      "DELETE /api/admin/projects/p1/members/u1": fail(409, "у проекта остаётся заказчик"),
    });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Убрать" }));
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("у проекта остаётся заказчик");
  });

  it("adds a member picked from the database; the studio's own people are greyed out", async () => {
    const user = userEvent.setup();
    const inStudio = userRow({ id: "u5", name: "Сотрудник", space: { ...projectDetail().studio, kind: "studio", business: null, city: "", phone: "", folder: "", created: null } });
    const sent = stubApi({
      [DETAIL]: projectDetail(),
      "GET /api/admin/users?q=": [userRow({ id: "u4", name: "Заказчик" }), inStudio],
      "POST /api/admin/projects/p1/members": projectDetail({ members: [{ user: person({ id: "u4", name: "Заказчик" }), role: "client", since: null }] }),
    });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "+ Добавить" }));
    expect(await screen.findByRole("button", { name: /Сотрудник.*в студии проекта/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Заказчик/ }));
    await user.click(screen.getByRole("button", { name: "Добавить" }));
    expect(sent.at(-1)).toMatchObject({ method: "POST", body: { user: "u4", role: "client" } });
    expect(await screen.findByText("Участники (1)")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("issues a code and shows it once", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [DETAIL]: projectDetail(), "POST /api/admin/projects/p1/codes": { code: "K7Q-2MX" } });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "+ Выдать" }));
    const form = screen.getByRole("dialog", { name: "Код доступа к проекту" });
    await user.click(within(form).getByRole("button", { name: "заказчик" }));
    await user.type(within(form).getByPlaceholderText("Кому (подпись в списке)"), "Иван");
    await user.click(within(form).getByRole("button", { name: "Выдать" }));
    expect(sent.find((r) => r.method === "POST")?.body).toEqual({ role: "client_code", label: "Иван", days: 30 });
    expect(await screen.findByRole("dialog", { name: "Код доступа" })).toHaveTextContent("K7Q-2MX");
  });

  it("revokes an active code and an active invite; others have no button", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [DETAIL]: projectDetail({
        codes: [
          { id: "c1", label: "Иван", role: "viewer", state: "active", uses: 2, created: null, expires: null, last_used: null },
          { id: "c2", label: "", role: "viewer", state: "expired", uses: 0, created: null, expires: null, last_used: null },
        ],
        invites: [invite({ id: "i1" }), invite({ id: "i2", state: "accepted", accepted_by: ivan })],
      }),
      "DELETE /api/admin/projects/p1/codes/c1": projectDetail(),
      "DELETE /api/admin/invites/i1": { ok: true },
    });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    expect(await screen.findByText("принял Иван")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Отозвать" })).toHaveLength(2);
    const [code, link] = screen.getAllByRole("button", { name: "Отозвать" });
    await user.click(link);
    expect(screen.getByText("Отозвать ссылку?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(sent.some((r) => r.method === "DELETE" && r.path === "/api/admin/invites/i1")).toBe(true);
    await user.click(code);
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(await screen.findByText("Кодов нет")).toBeInTheDocument();
  });

  it("opens support access for 72 hours with a reason and can take it back", async () => {
    const user = userEvent.setup();
    const granted = projectDetail({ support: [{ user: ivan, reason: "лист пустой", state: "active", expires: null }] });
    const sent = stubApi({
      [DETAIL]: projectDetail(),
      "GET /api/admin/users?q=": [userRow({ id: "u1", name: "Иван" })],
      "POST /api/admin/projects/p1/support": granted,
      "DELETE /api/admin/projects/p1/support/u1": projectDetail(),
    });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "+ Открыть доступ" }));
    await user.click(await screen.findByRole("button", { name: /Иван/ }));
    await user.type(screen.getByRole("textbox", { name: "Причина" }), "лист пустой");
    await user.click(screen.getByRole("button", { name: "Добавить" }));
    expect(sent.at(-1)?.body).toEqual({ user: "u1", reason: "лист пустой", hours: 72 });
    expect(await screen.findByText("«лист пустой»")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Снять" }));
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(await screen.findByText("Доступа поддержки нет")).toBeInTheDocument();
  });

  it("issues an invite link and reloads the project", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ [DETAIL]: projectDetail(), "POST /api/admin/projects/p1/invites": { url: "https://shtroba.app/i/xyz" } });
    render(<ProjectView id="p1" onChanged={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "+ Ссылка" }));
    await user.click(screen.getByRole("button", { name: "Выдать" }));
    expect(sent.find((r) => r.method === "POST")?.body).toEqual({ role: "client", email: null, days: 7 });
    expect(await screen.findByRole("dialog", { name: "Ссылка-приглашение" })).toHaveTextContent("https://shtroba.app/i/xyz");
    expect(sent.filter((r) => r.path === "/api/admin/projects/p1")).toHaveLength(2);
  });
});
