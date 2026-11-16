import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { page } from "@/shared/testData";
import { WallGrid } from "./index";

// The thumbnails are canvas drawings (thumb.ts, tested on its own): jsdom has no 2D context
vi.mock("./thumb", () => ({ THUMB_W: 160, THUMB_H: 100, drawThumb: vi.fn() }));
const { drawThumb } = await import("./thumb");

const walls = [
  { sheet: 4, key: "e:k.w1", box: [0, 0, 10, 10] as [number, number, number, number], title: "Кухня — стена 1" },
  { sheet: 4, key: "e:k.w2", box: [0, 0, 10, 10] as [number, number, number, number], title: "Кухня — стена 2" },
  { sheet: 5, key: "e:b.w1", box: [0, 0, 10, 10] as [number, number, number, number], title: "Спальня — стена 1" },
];
const pages = [{ index: 4, page: page({ stage: "elevations" }) }];

describe("WallGrid", () => {
  it("shows every wall by room with the open one focused; a card opens its wall", async () => {
    const onPick = vi.fn(), onClose = vi.fn();
    render(<WallGrid walls={walls} pages={pages} at={1} onPick={onPick} onClose={onClose} />);
    expect(screen.getByRole("region", { name: "Все стены" })).toBeInTheDocument();
    expect(screen.getByText("Стен: 3")).toBeInTheDocument();
    const kitchen = screen.getByRole("region", { name: "Кухня" });
    expect(within(kitchen).getByRole("button", { name: "Открыть: Кухня — стена 2" })).toHaveFocus();
    expect(drawThumb).toHaveBeenCalledTimes(2);  // the walls of a sheet that is loaded
    await userEvent.click(screen.getByRole("button", { name: "Открыть: Спальня — стена 1" }));
    expect(onPick).toHaveBeenCalledWith(2);
    await userEvent.click(screen.getByRole("button", { name: "Открыть: Кухня — стена 2" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("goes back by the button and by Esc", async () => {
    const onClose = vi.fn();
    render(<WallGrid walls={walls} pages={pages} at={0} onPick={vi.fn()} onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "← К стене" }));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
