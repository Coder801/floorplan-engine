import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WallPager } from "./index";

const walls = [
  { key: "e:k.w1", title: "Кухня — стена 1" }, { key: "e:k.w2", title: "Кухня — стена 2" },
  { key: "e:b.w1", title: "Спальня — стена 1" },
];

function open(at: number) {
  const props = { walls, at, onTurn: vi.fn(), onPick: vi.fn(), onAll: vi.fn() };
  return { ...props, ...render(<WallPager {...props} />) };
}

describe("WallPager", () => {
  it("turns to the neighbour walls; the ends are off", async () => {
    const { onTurn, rerender, ...props } = open(0);
    expect(screen.getByRole("button", { name: "Предыдущая стена" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Следующая стена" }));
    expect(onTurn).toHaveBeenCalledWith(1);
    rerender(<WallPager {...props} onTurn={onTurn} at={2} />);
    expect(screen.getByRole("button", { name: "Следующая стена" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Спальня — стена 1\s*· 3 \/ 3/ })).toBeInTheDocument();
  });

  it("the wall name lists the walls by room for a quick jump", async () => {
    const user = userEvent.setup();
    const { onPick } = open(0);
    await user.click(screen.getByRole("button", { name: /Кухня — стена 1/ }));
    const list = screen.getByRole("listbox", { name: "Стены" });
    const kitchen = within(list).getByRole("group", { name: "Кухня" });
    expect(within(kitchen).getByRole("option", { name: /Стена 1/ })).toHaveAttribute("aria-selected", "true");
    await user.click(within(list).getByRole("group", { name: "Спальня" }).querySelector("button")!);
    expect(onPick).toHaveBeenCalledWith(2);
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
  });

  it("opens the overview of all walls", async () => {
    const { onAll } = open(1);
    await userEvent.click(screen.getByRole("button", { name: "Все стены" }));
    expect(onAll).toHaveBeenCalledOnce();
  });
});
