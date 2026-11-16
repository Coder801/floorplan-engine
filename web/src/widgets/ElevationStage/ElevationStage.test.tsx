import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { elevation } from "@/shared/testData";
import { ElevationStage } from "./index";

// The elevation is drawn by its canvas engine (engine/elevation, tested on its own): here a
// stand-in that records what the React side asks of it
const views: { setData: ReturnType<typeof vi.fn>; zoomTo: ReturnType<typeof vi.fn>; fit: ReturnType<typeof vi.fn>;
               destroy: ReturnType<typeof vi.fn>; onZoom?: (z: unknown) => void; mode: string }[] = [];
vi.mock("@/engine/elevation/ElevationView", () => ({
  ElevationView: class {
    setData = vi.fn(); zoomTo = vi.fn(); fit = vi.fn(); destroy = vi.fn(); onZoom?: (z: unknown) => void; mode: string;
    constructor(_c: unknown, _p: unknown, _e: unknown, _m: unknown, mode: string) { this.mode = mode; views.push(this); }
  },
}));

describe("ElevationStage", () => {
  it("draws the wall in its canvas; zoom buttons drive it and its zoom comes back to the scale bar", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ElevationStage elevation={elevation()} withMap={false} />);
    const v = views.at(-1)!;
    expect(screen.getByLabelText("Развёртка: Кухня · стена 1")).toBeInTheDocument();
    expect(screen.getByText(/потолок 2700\* — допущение/)).toBeInTheDocument();
    act(() => v.onZoom?.({ step: 1, label: "150%", pxPerMm: 0.1 }));
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByLabelText(/^Линейка:/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Увеличить" }));
    expect(v.zoomTo).toHaveBeenCalledWith(2);
    await user.click(screen.getByRole("button", { name: "Вся стена" }));
    expect(v.fit).toHaveBeenCalledOnce();
    unmount();
    expect(v.destroy).toHaveBeenCalledOnce();
  });

  it("isometry is a toggle, remembered in the browser, without the scale bar", async () => {
    const user = userEvent.setup();
    const first = render(<ElevationStage elevation={elevation()} withMap />);
    const v = views.at(-1)!;
    act(() => v.onZoom?.({ step: 0, label: "100%", pxPerMm: 0.1 }));
    await user.click(screen.getByRole("button", { name: "Изометрия" }));
    expect(screen.getByRole("button", { name: "Изометрия", pressed: true })).toBeInTheDocument();
    expect(v.setData).toHaveBeenLastCalledWith(expect.anything(), true, "iso");
    expect(localStorage.getItem("elevMode")).toBe("iso");
    expect(screen.queryByLabelText(/^Линейка:/)).toBeNull();
    first.unmount();
    render(<ElevationStage elevation={elevation()} withMap />);
    expect(views.at(-1)!.mode).toBe("iso");
  });
});
