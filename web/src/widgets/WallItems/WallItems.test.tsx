import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetSelection, view } from "@/shared/store";
import { elevation } from "@/shared/testData";
import { WallItems } from "./index";

beforeEach(() => { resetSelection(); view.set({ wallLayers: { electrical: true, water: true } }); });

describe("WallItems", () => {
  it("lists the points and the water by section; a row lights and pins its object", async () => {
    const user = userEvent.setup();
    render(<WallItems wall={elevation()} />);
    expect(screen.getByText("Вид изнутри · за стеной: коридор · длина 3600, потолок 2700* мм")).toBeInTheDocument();
    const electrical = screen.getByRole("heading", { name: /Электрика/ }).closest("section")!;
    const socket = within(electrical).getByText("Розетка").closest("li")!;
    expect(socket).toHaveTextContent("QF4 · от К1");
    expect(socket).toHaveTextContent("400 × 300");
    await user.hover(socket);
    expect(view.get().lit).toEqual(new Set(["point:p1"]));
    await user.click(socket);
    expect(view.get().pinned).toBe("point:p1");
    await user.click(socket);
    expect(view.get().pinned).toBeNull();
    const water = screen.getByRole("heading", { name: /Вода/ }).closest("section")!;
    expect(within(water).getByText("Мойка")).toBeInTheDocument();
  });

  it("the eye hides a layer on the elevation", async () => {
    render(<WallItems wall={elevation()} />);
    await userEvent.click(screen.getByRole("button", { name: "Скрыть: Вода" }));
    expect(view.get().wallLayers).toEqual({ electrical: true, water: false });
  });

  it("a point opens the wiring sheet at its line", async () => {
    const onWiring = vi.fn();
    render(<WallItems wall={elevation()} onWiring={onWiring} />);
    await userEvent.click(screen.getByRole("button", { name: "На проводке →" }));
    expect(onWiring).toHaveBeenCalledWith("point:p1");
    expect(view.get().pinned).toBeNull();  // the click does not pin the row
  });

  it("a wall with only chases says so", () => {
    render(<WallItems wall={elevation({ points: [], water: [] })} />);
    expect(screen.getByText("На стене только штробы")).toBeInTheDocument();
  });
});
