import { describe, expect, it } from "vitest";
import { addPhotos, contextOf, failureOf, PHOTO_MAX, PHOTOS_MAX, sheetOf, TEXT_MAX, textOk } from "./feedback";

const file = (name: string, type: string, size = 10) => new File([new Uint8Array(size)], name, { type });

describe("текст отзыва", () => {
  it("нужен хоть один знак и не больше предела", () => {
    expect(textOk("")).toBe(false);
    expect(textOk("   \n")).toBe(false);
    expect(textOk("кнопка не жмётся")).toBe(true);
    expect(textOk("a".repeat(TEXT_MAX))).toBe(true);
    expect(textOk("a".repeat(TEXT_MAX + 1))).toBe(false);
    expect(textOk(`  ${"a".repeat(TEXT_MAX)}  `)).toBe(true);  // пробелы по краям не считаются
  });
});

describe("скриншоты", () => {
  it("берёт картинки по порядку, лишние и чужие — отказом по имени", () => {
    const got = addPhotos([], [file("a.png", "image/png"), file("b.pdf", "application/pdf"), file("c.JPG", "IMAGE/JPEG")]);
    expect(got.photos.map((f) => f.name)).toEqual(["a.png", "c.JPG"]);
    expect(got.refused).toEqual([{ name: "b.pdf", reason: "type" }]);
  });
  it("не больше трёх вместе с уже приложенными", () => {
    const have = [file("1.png", "image/png"), file("2.webp", "image/webp")];
    const got = addPhotos(have, [file("3.png", "image/png"), file("4.png", "image/png")]);
    expect(got.photos).toHaveLength(PHOTOS_MAX);
    expect(got.refused).toEqual([{ name: "4.png", reason: "count" }]);
    expect(have).toHaveLength(2);  // исходный список не меняется
  });
  it("большой файл — отказ по размеру", () => {
    const big = { name: "big.png", type: "image/png", size: PHOTO_MAX + 1 } as File;
    expect(addPhotos([], [big]).refused).toEqual([{ name: "big.png", reason: "size" }]);
  });
});

describe("контекст", () => {
  it("вкладка, не лист, — словом, лист — именем, развёртка — со стеной", () => {
    expect(sheetOf({})).toBeNull();
    expect(sheetOf({ info: true, sheet: "plan" })).toBe("overview");
    expect(sheetOf({ estimate: true, sheet: "wiring" })).toBe("estimate");
    expect(sheetOf({ work: true })).toBe("work");
    expect(sheetOf({ source: "plan.pdf", info: true })).toBe("source:plan.pdf");
    expect(sheetOf({ sheet: "electrical" })).toBe("electrical");
    expect(sheetOf({ sheet: "elevations", wall: "kitchen.w2" })).toBe("elevations · kitchen.w2");
  });
  it("экран — ширина×высота, плотность — только если не 1", () => {
    const where = { path: "/#kv42", width: 1440, height: 900, dpr: 1, userAgent: "UA" };
    expect(contextOf("plan", "0.5.1 (b1)", where)).toEqual({
      sheet: "plan", path: "/#kv42", version: "0.5.1 (b1)", viewport: "1440×900", user_agent: "UA",
    });
    expect(contextOf(null, "v", { ...where, width: 390.4, height: 844, dpr: 3 }).viewport).toBe("390×844@3");
    expect(contextOf(null, "v", { ...where, dpr: 1.3333 }).viewport).toBe("1440×900@1.33");
  });
});

describe("отказ сервера", () => {
  it("по статусу — своё объяснение", () => {
    expect(failureOf(401)).toBe("auth");
    expect(failureOf(429)).toBe("rate");
    expect(failureOf(413)).toBe("tooBig");
    expect(failureOf(415)).toBe("type");
    expect(failureOf(500)).toBe("failed");
    expect(failureOf(null)).toBe("failed");  // сеть
  });
});
