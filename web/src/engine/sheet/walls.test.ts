import { describe, expect, it } from "vitest";
import type { Item, Page } from "@/shared/types";
import { splitTitle, wallPages, wallRooms, wallSheet } from "./walls";

const item = (o: string | undefined, d: string): Item => ({ k: "s", c: "#000000", l: "E-ELEV", o, d });
const page = (items: Item[], objects: Page["objects"] = {}): Page =>
  ({ name: "07", format: "A2", size: [594, 420], background: "#fff", items, objects });

describe("wallPages", () => {
  it("развёртка — габарит её примитивов с полем и имя из карточки", () => {
    const p = page(
      [item("elevation:bath.w1", "M10 10L50 10"), item("elevation:bath.w1", "M10 60L20 60"),
       item("elevation:bath.w2", "M100 10L140 70"), item(undefined, "M0 0L594 420")],
      { "elevation:bath.w1": { title: "Санвузол — стена 1", rows: [] } },
    );
    const [a, b] = wallPages([{ index: 7, page: p }]);
    expect(a).toEqual({ sheet: 7, key: "elevation:bath.w1", box: [6, 6, 54, 64], title: "Санвузол — стена 1" });
    expect(b.title).toBe("bath.w2");  // no card: the key
  });

  it("листы по порядку, развёртки листа — по первому примитиву", () => {
    const keys = wallPages([
      { index: 7, page: page([item("elevation:b.w2", "M0 0L1 1"), item("elevation:a.w1", "M0 0L1 1")]) },
      { index: 8, page: page([item("elevation:c.w1", "M0 0L1 1")]) },
    ]).map((w) => `${w.sheet}:${w.key}`);
    expect(keys).toEqual(["7:elevation:b.w2", "7:elevation:a.w1", "8:elevation:c.w1"]);
  });

  it("лист развёртки — только её примитивы и её видовой экран", () => {
    const p = page([item("elevation:a.w1", "M10 10L20 20"), item("elevation:a.w2", "M0 10L5 20"), item(undefined, "M0 0L9 9")]);
    const [w] = wallPages([{ index: 7, page: p }]);
    const [x0, y0, x1, y1] = w.box;
    const view = wallSheet(p, w).view!;
    expect(view.slice(1)).toEqual([y0, x1, y1]);
    expect(view[0]).toBeLessThan(x0);  // on the left, a margin for the mini map
    expect(wallSheet(p, w).items.map((i) => i.o)).toEqual(["elevation:a.w1"]);
  });
});

describe("wallRooms", () => {
  it("splits titles into room and wall", () => {
    expect(splitTitle("Санвузол 2 (пральня) — стіна 2")).toEqual(["Санвузол 2 (пральня)", "стіна 2"]);
    expect(splitTitle("w3")).toEqual(["", "w3"]);
  });

  it("groups walls by room in sheet order; a room met again later is a new group", () => {
    const rooms = wallRooms([
      { title: "Кухня — стена 1" }, { title: "Кухня — стена 2" }, { title: "Ванная — стена 1" }, { title: "Кухня — стена 3" },
    ]);
    expect(rooms).toEqual([
      { room: "Кухня", items: [{ index: 0, wall: "стена 1" }, { index: 1, wall: "стена 2" }] },
      { room: "Ванная", items: [{ index: 2, wall: "стена 1" }] },
      { room: "Кухня", items: [{ index: 3, wall: "стена 3" }] },
    ]);
  });
});
