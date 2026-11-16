import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { stubApi } from "@/shared/testApi";
import { event, person } from "@/shared/testData";
import { EventTable, Events } from "./Events";

const ivan = person({ id: "u1", name: "Иван" });
const olga = person({ id: "u2", name: "Ольга" });
const rows = [
  event({ id: "e1", action: "login", user: ivan, project: "p1" }),
  event({ id: "e2", action: "invite", user: olga, subject: ivan, studio: { id: "s1", name: "Ампер" }, project: "p1", payload: { role: "client" } }),
];

describe("EventTable", () => {
  it("links the author, the subject and the studio; a click on a row opens its payload", async () => {
    const user = userEvent.setup();
    render(<EventTable rows={rows} />);
    const row = screen.getByText("приглашение").closest("tr")!;
    expect(within(row).getByRole("link", { name: "Ольга" })).toHaveAttribute("href", "#/users/u2");
    expect(within(row).getByRole("link", { name: "Иван" })).toHaveAttribute("href", "#/users/u1");
    expect(within(row).getByRole("link", { name: "«Ампер»" })).toHaveAttribute("href", "#/studios/s1");
    await user.click(screen.getByText("приглашение"));
    expect(within(row).getByText(/"role": "client"/)).toBeInTheDocument();
    await user.click(screen.getByText("приглашение"));
    expect(within(row).queryByText(/"role"/)).toBeNull();
  });

  it("compact drops the project column", () => {
    render(<EventTable rows={rows} compact />);
    expect(screen.queryByRole("columnheader", { name: "Проект" })).toBeNull();
  });
});

describe("Events", () => {
  it("filters by the project and author from the address, by action and loads more", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      "GET /api/admin/events?project=p1&user=u1&limit=200": rows,
      "GET /api/admin/events?project=p1&user=u1&limit=500": rows,
    });
    render(<Events params={new URLSearchParams("project=p1&user=u1")} />);
    expect(await screen.findByRole("cell", { name: "вход" })).toBeInTheDocument();
    expect(screen.getByText(/автор Иван/)).toBeInTheDocument();
    // × of a filter keeps the other one
    const [dropProject, dropAuthor] = screen.getAllByRole("link", { name: "×" });
    expect(dropProject).toHaveAttribute("href", "#/events?user=u1");
    expect(dropAuthor).toHaveAttribute("href", "#/events?project=p1");

    const [actions, limit] = screen.getAllByRole("combobox");
    await user.selectOptions(actions, "приглашение");
    expect(screen.queryByRole("cell", { name: "вход" })).toBeNull();
    expect(screen.getByRole("cell", { name: "приглашение" })).toBeInTheDocument();
    await user.selectOptions(limit, "последние 500");
    expect(sent.at(-1)?.path).toBe("/api/admin/events?project=p1&user=u1&limit=500");
  });
});
