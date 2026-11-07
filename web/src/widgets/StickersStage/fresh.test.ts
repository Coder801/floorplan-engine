import { describe, expect, it } from "vitest";
import type { PanelSticker, PanelStickers } from "@/shared/types";
import { freshStickers } from "./fresh";

const item = { id: "QF1", short_id: "1", number: "M0 0", short_number: "M1 1", name: "M2 2", color: "#000000" } as PanelSticker;
const sheet = (items: PanelSticker[]) => ({ items }) as PanelStickers;

describe("freshStickers", () => {
  it("keeps a build of the current format", () => {
    const stickers = sheet([item]);
    expect(freshStickers(stickers)).toBe(stickers);
  });

  it("keeps a device whose name is empty", () => {
    expect(freshStickers(sheet([{ ...item, name: "" }]))).toBeDefined();
  });

  it("drops stickers of an earlier format and a build without them", () => {
    const early = { id: "QF1", row: 0, title: "Розетки", icon: "plug", text: ["Розетки"] } as unknown as PanelSticker;
    expect(freshStickers(sheet([early]))).toBeUndefined();
    expect(freshStickers(undefined)).toBeUndefined();
  });
});
