import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { fail, stubApi } from "@/shared/testApi";
import { feedbackPage, studioDetail, studioRow } from "@/shared/testData";

const owner = { id: "u1", name: "Владелец", email: null, phone: null, superuser: true };
const COMMON = {
  "GET /api/admin/feedback?status=new&offset=0&limit=1": feedbackPage([], { counts: { new: 2, seen: 0, done: 0 } }),
  "GET /api/admin/summary": { studios: 1, personal: 0, users: 1, projects: 0, sessions: 1 },
  "GET /api/admin/events?limit=15": [],
};

describe("App", () => {
  it("lets only the platform owner in and explains why to others", async () => {
    stubApi({ "GET /api/auth/me": { auth: false, user: null } });
    const { unmount } = render(<App />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    expect(await screen.findByText(/Вход в сервис выключен/)).toBeInTheDocument();
    unmount();

    stubApi({ "GET /api/auth/me": { auth: true, user: null } });
    const second = render(<App />);
    expect(await screen.findByText("Сначала войдите в просмотр.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть просмотр и войти" })).toHaveAttribute("href", "/");
    second.unmount();

    stubApi({ "GET /api/auth/me": { auth: true, user: { ...owner, superuser: false } } });
    render(<App />);
    expect(await screen.findByText("Админка — только для владельца платформы.")).toBeInTheDocument();
  });

  it("shows the error of the login check", async () => {
    stubApi({ "GET /api/auth/me": fail(502, "сервис недоступен") });
    render(<App />);
    expect(await screen.findByText("сервис недоступен")).toBeInTheDocument();
  });

  it("the owner gets the sections with the count of new feedback; the address picks the section", async () => {
    location.hash = "";
    stubApi({
      ...COMMON,
      "GET /api/auth/me": { auth: true, user: owner },
      "GET /api/admin/studios": [studioRow()],
      "GET /api/admin/studios/s1": studioDetail(),
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Сводка" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Отзывы2" })).toHaveAttribute("href", "#/feedback");
    expect(screen.getByText("Владелец")).toBeInTheDocument();

    await act(async () => {
      location.hash = "#/studios";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("link", { name: /Ампер/ })).toBeInTheDocument();
    expect(screen.getByText("Выберите запись в списке")).toBeInTheDocument();

    await act(async () => {
      location.hash = "#/studios/s1";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: "Ампер" })).toBeInTheDocument();
    expect(screen.queryByText("Выберите запись в списке")).toBeNull();
  });

  it("the clients take the whole width", async () => {
    location.hash = "#/clients";
    stubApi({ ...COMMON, "GET /api/auth/me": { auth: true, user: owner }, "GET /api/admin/clients?q=": [] });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Клиенты" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Клиенты" })).toHaveAttribute("href", "#/clients");
    expect(screen.queryByText("Выберите запись в списке")).toBeNull();
    location.hash = "";
  });
});
