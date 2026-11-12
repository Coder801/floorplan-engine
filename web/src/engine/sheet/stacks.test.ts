import { describe, expect, it } from "vitest";
import type { Box } from "@/shared/types";
import { grownBox, isSymbol, openStacks, pointStacks, symbolCenters } from "./stacks";

// A socket symbol 4×2 mm centred at (x, y)
const socket = (id: string, x: number, y: number) => ({ o: `point:${id}`, l: "E-SOCKET", box: [x - 2, y - 1, x + 2, y + 1] as Box });
const sw = (id: string, x: number, y: number) => ({ o: `point:${id}`, l: "E-SWITCH", box: [x - 1.5, y - 1.5, x + 1.5, y + 1.5] as Box });
const label = (ids: string, x: number, y: number) => ({ o: `label:${ids}`, l: "E-TEXT", box: [x - 3, y - 1, x + 3, y + 1] as Box });

describe("socket stacks", () => {
  it("a stack from the wall into the room: the socket at the wall stays, the rest hide in it", () => {
    // The wall is above, the stack goes down, the label past the last socket
    const items = [socket("a", 100, 10), socket("b", 100, 13.4), socket("c", 100, 16.8), label("a,b,c", 100, 25)];
    const [st] = pointStacks(items);
    expect(st.anchor).toBe("point:a");
    expect(st.rest).toEqual(["point:b", "point:c"]);
    expect(st.shift["point:c"][0]).toBeCloseTo(0);
    expect(st.shift["point:c"][1]).toBeCloseTo(-6.8);
    expect(st.box).toEqual([98, 9, 102, 17.8]);
    expect(st.count).toEqual([102, 11]);  // the room is below: the lower corner
  });

  it("the label order does not matter: the socket at the wall is the farthest from the label", () => {
    const items = [socket("a", 100, 16.8), socket("b", 100, 13.4), socket("c", 100, 10), label("a,b,c", 100, 3)];
    const [st] = pointStacks(items);
    expect(st.anchor).toBe("point:a");
    expect(st.rest).toEqual(["point:b", "point:c"]);
  });

  it("sockets side by side along the wall are other places, not a stack", () => {
    // Both at the wall (x = 451), 6 mm apart along it; the label is to the left
    const items = [socket("a", 451, 193), socket("b", 451, 199), label("a,b", 444, 196)];
    expect(pointStacks(items)).toEqual([]);
  });

  it("switches stack too, apart from the socket of the same place", () => {
    // The outlet at the wall, three switches behind it, the label past the last one
    const items = [socket("o", 100, 10), sw("a", 100, 13.4), sw("b", 100, 18), sw("c", 100, 22.6), label("o,a,b,c", 100, 30)];
    const [st, ...more] = pointStacks(items);
    expect(more).toEqual([]);  // one socket is no stack
    expect(st.key).toBe("label:o,a,b,c|E-SWITCH");
    expect(st.anchor).toBe("point:a");
    expect(st.rest).toEqual(["point:b", "point:c"]);
  });

  it("the stacks of one place open together", () => {
    const items = [socket("a", 100, 10), socket("b", 100, 13.4), sw("c", 100, 17), sw("d", 100, 21), label("a,b,c,d", 100, 30)];
    const stacks = pointStacks(items);
    const both = new Set(["label:a,b,c,d|E-SOCKET", "label:a,b,c,d|E-SWITCH"]);
    expect(openStacks(stacks, null, ["point:d"])).toEqual(both);
    expect(openStacks(stacks, "label:a,b,c,d", [])).toEqual(both);
  });

  it("a switch in the frame is not a socket: one socket is no stack", () => {
    const items = [socket("a", 100, 10), { o: "point:sw", l: "E-SWITCH", box: [98, 12, 102, 14] as Box }, label("a,sw", 100, 20)];
    expect(pointStacks(items)).toEqual([]);
  });

  it("opens by the pointer, a socket under the cursor, selected or lit", () => {
    const items = [socket("a", 100, 10), socket("b", 100, 13.4), label("a,b", 100, 20)];
    const stacks = pointStacks(items);
    expect(openStacks(stacks, null, [null, null, null])).toEqual(new Set());
    const key = "label:a,b|E-SOCKET";
    expect(openStacks(stacks, "label:a,b", [])).toEqual(new Set([key]));
    expect(openStacks(stacks, null, ["point:a"])).toEqual(new Set([key]));
    expect(openStacks(stacks, null, [new Set(["point:b"])])).toEqual(new Set([key]));
    expect(openStacks(stacks, null, [new Set(["point:x"])])).toEqual(new Set());
  });
});

describe("symbols on screen", () => {
  it("points and boxes grow about their centre, the panel and labels do not", () => {
    expect(isSymbol({ o: "point:a", l: "E-SOCKET" })).toBe(true);
    expect(isSymbol({ o: "box:b1", l: "W-BOX" })).toBe(true);
    expect(isSymbol({ o: "board:board", l: "E-BOARD" })).toBe(false);
    expect(isSymbol({ o: "label:a", l: "E-TEXT" })).toBe(false);
    expect(isSymbol({ o: "led_strip:s", l: "E-LED" })).toBe(false);
    const c = symbolCenters([socket("a", 10, 20), { o: "point:a", l: "E-SOCKET", box: [8, 21, 12, 23] }]).get("point:a")!;
    expect(c).toEqual([10, 21]);
    expect(grownBox([8, 19, 12, 23], c, 1.25)).toEqual([7.5, 18.5, 12.5, 23.5]);
  });
});
