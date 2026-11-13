import { describe, expect, it } from "vitest";
import type { Item, Page } from "@/shared/types";
import { isPlane, ownerOf, splitTitle, wallPages, wallRooms, wallSheet } from "./walls";

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
      { room: "Кухня", items: [{ index: 0, wall: "Стена 1" }, { index: 1, wall: "Стена 2" }] },
      { room: "Ванная", items: [{ index: 2, wall: "Стена 1" }] },
      { room: "Кухня", items: [{ index: 3, wall: "Стена 3" }] },
    ]);
  });

  it("под названием помещения имя — с большой буквы; имя без помещения не меняется", () => {
    expect(wallRooms([{ title: "Спальня — потолок" }, { title: "w3" }])).toEqual([
      { room: "Спальня", items: [{ index: 0, wall: "Потолок" }] },
      { room: "", items: [{ index: 1, wall: "w3" }] },
    ]);
  });
});

describe("ceiling pages", () => {
  it("a scale value belongs to its ceiling page", () => {
    expect(ownerOf("dim:bath.ceiling.x1450")).toBe("elevation:bath.ceiling");
    expect(ownerOf("elevation:bath.w3")).toBe("elevation:bath.w3");
    expect(ownerOf("wire:wire_1")).toBeNull();
    expect(isPlane("elevation:bath.ceiling") && isPlane("elevation:bath.floor")).toBe(true);
    expect(isPlane("elevation:bath.w3")).toBe(false);
  });
  it("the ceiling page takes its scale values into its box and drawing", () => {
    const items = [
      { k: "s", d: "M0 0L10 10", o: "elevation:bath.ceiling" },
      { k: "s", d: "M0 20L10 30", o: "dim:bath.ceiling.x1450" },
      { k: "s", d: "M50 50L60 60", o: "elevation:bath.w1" },
    ] as unknown as Item[];
    const page = { items } as unknown as Page;
    const [ceiling] = wallPages([{ index: 7, page }]);
    expect(ceiling.key).toBe("elevation:bath.ceiling");
    expect(ceiling.box[3]).toBeGreaterThanOrEqual(30);  // the scale is inside the page box
    expect(wallSheet(page, ceiling).items.map((it) => it.o)).toEqual(["elevation:bath.ceiling", "dim:bath.ceiling.x1450"]);
  });
});
