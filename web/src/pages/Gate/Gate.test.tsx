import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { me, user } from "@/shared/testData";
import type { Account } from "@/widgets/Settings";
import { Gate } from "./index";

const inside = vi.fn((account: Account | null) => <p>Проекты{account ? `: ${account.name}` : ""}</p>);
beforeEach(() => inside.mockClear());

describe("Gate", () => {
  it("is open when login is off on the server", async () => {
    stubApi({ "GET /api/auth/me": { auth: false } });
    render(<Gate>{inside}</Gate>);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    expect(await screen.findByText("Проекты")).toBeInTheDocument();
    expect(inside).toHaveBeenLastCalledWith(null);
  });

  it("lets a logged-in person in with their account", async () => {
    stubApi({ "GET /api/auth/me": me({ feedback: true }) });
    render(<Gate>{inside}</Gate>);
    expect(await screen.findByText("Проекты: Иван")).toBeInTheDocument();
    expect(inside.mock.lastCall?.[0]).toMatchObject({ id: "u1", plan: "pro", space: "Ампер", visitor: false, code: false, feedback: true, prices: true });
  });

  it("passes no price-list right to an installer", async () => {
    stubApi({ "GET /api/auth/me": me({ user: user({ prices: false }) }) });
    render(<Gate>{inside}</Gate>);
    expect(await screen.findByText("Проекты: Иван")).toBeInTheDocument();
    expect(inside.mock.lastCall?.[0]).toMatchObject({ plan: "pro", prices: false });
  });

  it("shows only the configured ways in; no way says so", async () => {
    stubApi({ "GET /api/auth/me": { auth: true, user: null, google: true, email: true } });
    const { unmount } = render(<Gate>{inside}</Gate>);
    expect(await screen.findByRole("heading", { level: 1, name: "Вход" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Продолжить с Google" })).toHaveAttribute("href", "/api/auth/google/login");
    expect(screen.getByRole("textbox", { name: "Почта" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Войти через Telegram" })).toBeNull();
    expect(screen.getByRole("button", { name: "Почему без паролей?" })).toBeInTheDocument();
    expect(inside).not.toHaveBeenCalled();
    unmount();

    stubApi({ "GET /api/auth/me": { auth: true, user: null } });
    render(<Gate>{inside}</Gate>);
    expect(await screen.findByText("Вход через Telegram, Google и почту ещё не настроен на сервере.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Код от студии" })).toBeInTheDocument();
  });

  it("an access code opens its project", async () => {
    const user = userEvent.setup();
    let calls = 0;
    stubApi({
      "GET /api/auth/me": () => (++calls === 1 ? { auth: true, user: null } : { auth: true, code: { project: "p1", name: "Иван" } }),
      "POST /api/auth/code": { ok: true, project: "p1" },
    });
    render(<Gate>{inside}</Gate>);
    await user.type(await screen.findByRole("textbox", { name: "Код от студии" }), "K7Q2MXAB{Enter}");
    expect(await screen.findByText("Проекты: Иван")).toBeInTheDocument();
    expect(location.hash).toBe("#p1");
    expect(inside.mock.lastCall?.[0]).toMatchObject({ code: true, id: null });
  });

  it("says who invited and accepts the invite after login", async () => {
    history.replaceState(null, "", "/?invite=tok#");
    let calls = 0;
    const sent = stubApi({
      "GET /api/auth/me": () => (++calls === 1 ? { auth: true, user: null, google: true } : me()),
      "GET /api/invites/tok": { role: "installer", project: "Квартира 42" },
      "POST /api/invites/tok/accept": { role: "installer", project: "p1" },
    });
    const { unmount } = render(<Gate>{inside}</Gate>);
    expect(await screen.findByText(/Вас пригласили в проект «Квартира 42» как монтажник/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Продолжить с Google" })).toHaveAttribute("href", "/api/auth/google/login?invite=tok");
    unmount();

    render(<Gate>{inside}</Gate>);  // back from Google: logged in now
    await vi.waitFor(() => expect(sent.some((r) => r.path === "/api/invites/tok/accept")).toBe(true));
    await vi.waitFor(() => expect(location.search).toBe(""));
    expect(location.hash).toBe("#p1");
  });

  it("shows a login error from the address", async () => {
    history.replaceState(null, "", "/?auth_error=Google%20отказал");
    stubApi({ "GET /api/auth/me": { auth: true, user: null } });
    render(<Gate>{inside}</Gate>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Google отказал");
  });

  it("the first login asks who you are: «Мой ремонт» at once, a firm by its form", async () => {
    const userEv = userEvent.setup();
    let chosen = false;
    const sent = stubApi({
      "GET /api/auth/me": () => (chosen ? me() : me({ user: user({ account_type: null, space: null }) })),
      "POST /api/auth/account-type": () => { chosen = true; return user({ account_type: "client" }); },
    });
    render(<Gate>{inside}</Gate>);
    expect(await screen.findByRole("heading", { level: 1, name: "Кто вы?" })).toBeInTheDocument();
    await userEv.click(screen.getByRole("button", { name: /Фирма/ }));
    expect(screen.getByRole("heading", { level: 1, name: "Регистрация фирмы" })).toBeInTheDocument();
    await userEv.click(screen.getByRole("button", { name: "Назад" }));
    await userEv.click(screen.getByRole("button", { name: /Мой ремонт/ }));
    expect(sent.find((r) => r.method === "POST")?.body).toEqual({ type: "client" });
    expect(await screen.findByText("Проекты: Иван")).toBeInTheDocument();
  });

  it("logs out from the account step", async () => {
    const userEv = userEvent.setup();
    const sent = stubApi({
      "GET /api/auth/me": me({ user: user({ account_type: null }) }),
      "POST /api/auth/logout": { ok: true },
    });
    render(<Gate>{inside}</Gate>);
    await userEv.click(await screen.findByRole("button", { name: "Выйти" }));
    expect(sent.some((r) => r.path === "/api/auth/logout")).toBe(true);
  });

  it("debug ways in: development login and a guest", async () => {
    const userEv = userEvent.setup();
    const sent = stubApi({
      "GET /api/auth/me": { auth: true, user: null, dev: true, visitor_allowed: true },
      "POST /api/auth/visitor": fail(403, "Гостей нет"),
    });
    render(<Gate>{inside}</Gate>);
    expect(await screen.findByRole("button", { name: "Зайти для разработки" })).toBeInTheDocument();
    await userEv.click(screen.getByRole("button", { name: "Войти как гость (отладка)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Гостей нет");
    expect(sent.some((r) => r.path === "/api/auth/visitor")).toBe(true);
  });

  it("a failed check of the login shows the error", async () => {
    stubApi({ "GET /api/auth/me": fail(502, "Сервер недоступен") });
    render(<Gate>{inside}</Gate>);
    expect(await screen.findByText("Сервер недоступен")).toBeInTheDocument();
  });
});
