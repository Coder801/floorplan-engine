import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { clientRow, person, projectRow } from "@/shared/testData";
import { Clients } from "./Clients";

const LIST = "GET /api/admin/clients?q=";

describe("Clients", () => {
  it("lists clients with their project and studio and filters by kind", async () => {
    const user = userEvent.setup();
    stubApi({
      [LIST]: [
        clientRow(),
        clientRow({
          user: person({ id: "u2", name: "Ольга", email: null, phone: "+380501112233" }), kind: "personal",
          project: projectRow({ id: "p2", name: "Своя квартира", studio: { id: "s2", name: "Ремонт Ольги" } }),
          studio: { id: "s2", name: "Ремонт Ольги" },
        }),
        clientRow({ user: person({ id: "u3", name: "Новичок" }), kind: "none", project: null, studio: null }),
      ],
    });
    render(<Clients />);
    const ivan = (await screen.findByRole("link", { name: "Иван Петров" })).closest("tr")!;
    expect(screen.getByRole("link", { name: "Иван Петров" })).toHaveAttribute("href", "#/users/u1");
    expect(within(ivan).getByText("Клиент студии")).toBeInTheDocument();
    expect(within(ivan).getByRole("link", { name: "Квартира на Нагорной" })).toHaveAttribute("href", "#/projects/p1");
    expect(within(ivan).getByRole("link", { name: "«Ампер»" })).toHaveAttribute("href", "#/studios/s1");
    const olga = screen.getByRole("link", { name: "Ольга" }).closest("tr")!;
    expect(within(olga).getByText("+380501112233")).toBeInTheDocument();
    expect(within(olga).getByText("сам")).toBeInTheDocument();
    expect(within(olga).queryByRole("link", { name: /Ремонт Ольги/ })).toBeNull();

    expect(screen.getByRole("button", { name: "все 3" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Без проекта 1" }));
    expect(screen.getAllByRole("row")).toHaveLength(2);  // the head and Новичок
    expect(screen.getByRole("link", { name: "Новичок" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Мой ремонт 1" }));
    expect(screen.getByRole("link", { name: "Ольга" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Иван Петров" })).toBeNull();
  });

  it("searches on the server after typing stops", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      [LIST]: [clientRow()],
      "GET /api/admin/clients?q=%D0%BD%D0%B5%D1%82": [],
    });
    render(<Clients />);
    await screen.findByRole("link", { name: "Иван Петров" });
    await user.type(screen.getByPlaceholderText("Имя, почта или телефон"), "нет");
    expect(await screen.findByText("Клиентов нет")).toBeInTheDocument();
    await vi.waitFor(() => expect(sent.at(-1)?.path).toBe("/api/admin/clients?q=%D0%BD%D0%B5%D1%82"));
  });

  it("shows the error of the list", async () => {
    stubApi({ [LIST]: fail(403, "только владелец") });
    render(<Clients />);
    expect(await screen.findByRole("alert")).toHaveTextContent("только владелец");
  });
});
