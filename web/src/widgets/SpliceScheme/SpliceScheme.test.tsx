import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetSelection, view } from "@/shared/store";
import { SpliceScheme } from "./index";
import { COLORS, crimped, hallSwitch, passSwitch, socketLoop } from "./mock";

beforeEach(() => resetSelection());

const joint = (letter: string) => screen.getByText(letter, { selector: "abbr" }).closest("li")!;

describe("SpliceScheme", () => {
  it("a socket of a loop: the feed, the cable on and a Wago 413 per conductor", () => {
    const { container } = render(<SpliceScheme splice={socketLoop()} colors={COLORS} />);
    const scheme = screen.getByRole("group", { name: "Схема подрозетника: соединений — 3" });
    expect(within(scheme).getByText("QF2 · 3x2.5 · 7 м")).toBeInTheDocument();
    expect(within(scheme).getByText("3x2.5 · 6,3 м")).toBeInTheDocument();
    for (const c of ["L", "N", "PE"]) {
      expect(joint(c).textContent).toBe(`${c}ввод3механизмWago 413`);
      expect(joint(c)).toHaveAttribute("title", "проводов в соединении: 3");
    }
    expect(screen.queryByText("С клемм механизма")).toBeNull();
    expect(screen.getByText("клеммы Wago 221 · подрозетник ≥60 мм")).toBeInTheDocument();
    // The feed and one cable out in the group colour, a dot per joint in the box
    const paths = [...container.querySelectorAll("path")];
    expect(paths).toHaveLength(2);
    expect(paths[1]).toHaveStyle({ stroke: COLORS.QF2 });
    expect(container.querySelectorAll("circle")).toHaveLength(4);
  });

  it("a switch: the cable to the lights comes off the terminals, neutral and earth joined", () => {
    render(<SpliceScheme splice={hallSwitch()} colors={COLORS} />);
    expect(screen.getByText("4x1.5 · 4 м · с клемм")).toBeInTheDocument();
    expect(joint("L").textContent).toBe("Lввод49механизмWago 413");
    expect(joint("N").textContent).toBe("Nввод5249Wago 413");
    const off = screen.getByText("С клемм механизма").closest("li")!;
    expect(off.textContent).toBe("52С клемм механизма");
  });

  it("a pass switch: only neutral and earth, 412 each", () => {
    render(<SpliceScheme splice={passSwitch()} />);
    expect(screen.queryByText("L", { selector: "abbr" })).toBeNull();
    expect(joint("N").textContent).toBe("Nввод61Wago 412");
    expect(joint("PE").textContent).toBe("PEввод61Wago 412");
  });

  it("crimp: a sleeve per joint, two devices", () => {
    render(<SpliceScheme splice={crimped()} />);
    expect(joint("L").textContent).toBe("Lввод3механизм ×2гильза");
    expect(screen.getByText("гильзы с термоусадкой · подрозетник ≥60 мм · механизмов: 2")).toBeInTheDocument();
  });

  it("without a feed: says so, the joints have no feed", () => {
    render(<SpliceScheme splice={hallSwitch({ in: null })} />);
    expect(screen.getByText("откуда питание — не указано")).toBeInTheDocument();
    expect(joint("N").textContent).toBe("N5249Wago 413");
  });

  it("the simple mode: where the cables go, without groups, cables and lengths", () => {
    render(<SpliceScheme splice={hallSwitch()} brief />);
    expect(screen.getByText("ЩР")).toBeInTheDocument();
    expect(screen.queryByText(/x1\.5/)).toBeNull();
    expect(joint("PE")).toBeInTheDocument();
  });

  it("a cable row lights its line and opens it; a joint row lights all its cables", async () => {
    const onOpen = vi.fn();
    const { unmount } = render(<SpliceScheme splice={hallSwitch()} onOpen={onOpen} canOpen={(k) => k !== "wire:wire_43"} />);
    // The line to the outlet is not on this sheet: its row is not a button
    expect(screen.queryByRole("button", { name: /Вивід кабелю/ })).toBeNull();
    const user = userEvent.setup();
    const lights = screen.getByRole("button", { name: /Світильник точковий/ });
    await user.hover(lights);
    expect(view.get().lit).toEqual(new Set(["wire:wire_39", "point:wardrobe_downlight_3"]));
    await user.click(lights);
    expect(onOpen).toHaveBeenCalledWith("wire:wire_39");
    await user.click(screen.getByRole("button", { name: /ЩР/ }));
    expect(onOpen).toHaveBeenLastCalledWith("wire:wire_42");
    await user.hover(joint("N"));
    expect(view.get().lit).toEqual(new Set(["wire:wire_42", "wire:wire_39", "wire:wire_43"]));
    await user.unhover(joint("N"));
    expect(view.get().lit).toBeNull();
    await user.hover(joint("L"));
    unmount();
    expect(view.get().lit).toBeNull();
  });
});
