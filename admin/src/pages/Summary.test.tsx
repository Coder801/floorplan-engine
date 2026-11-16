import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { event } from "@/shared/testData";
import { Summary } from "./Summary";

describe("Summary", () => {
  it("shows the counts as links to the lists and the last events", async () => {
    stubApi({
      "GET /api/admin/summary": { studios: 3, personal: 5, users: 12, projects: 9, sessions: 4 },
      "GET /api/admin/events?limit=15": [event({ action: "code_issue" })],
    });
    render(<Summary />);
    expect(await screen.findByRole("link", { name: "12людей" })).toHaveAttribute("href", "#/users");
    expect(screen.getByRole("link", { name: "9проектов" })).toHaveAttribute("href", "#/projects");
    expect(screen.getByRole("link", { name: "3фирм" })).toHaveAttribute("href", "#/studios");
    expect(await screen.findByText("код выдан")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "весь журнал" })).toHaveAttribute("href", "#/events");
  });

  it("shows the error of the counts", async () => {
    stubApi({ "GET /api/admin/summary": fail(403, "только владелец"), "GET /api/admin/events?limit=15": [] });
    render(<Summary />);
    expect(await screen.findByRole("alert")).toHaveTextContent("только владелец");
  });
});
