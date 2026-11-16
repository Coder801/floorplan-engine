import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { PageIndex } from "@/shared/page";
import { resetSelection, view } from "@/shared/store";
import { page } from "@/shared/testData";
import type { Scene } from "@/shared/types";
import { Filter3D } from "./index";

const scene = {
  floors: [{ key: "room:kitchen", rings: [], kind: "kitchen" }, { key: "room:bed", rings: [] }],
} as unknown as Scene;
const index = new PageIndex(page({ objects: { "room:kitchen": { title: "Кухня", rows: [] }, "room:bed": { title: "Спальня", rows: [] } } }));

beforeEach(() => resetSelection());

describe("Filter3D", () => {
  it("shows one room in 3D and clears the selection", async () => {
    const user = userEvent.setup();
    view.set({ selected: new Set(["x"]) });
    render(<Filter3D scene={scene} index={index} />);
    const select = screen.getByRole("button", { name: "Помещение" });
    expect(select).toHaveTextContent("Все помещения");
    await user.click(select);
    await user.click(screen.getByRole("option", { name: /Кухня/ }));
    expect(view.get().filter3d.room).toBe("kitchen");
    expect(view.get().selected).toBeNull();
    await user.click(screen.getByRole("button", { name: "Помещение" }));
    await user.click(screen.getByRole("option", { name: /Все помещения/ }));
    expect(view.get().filter3d.room).toBeNull();
  });
});
