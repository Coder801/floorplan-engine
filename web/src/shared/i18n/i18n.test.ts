import { describe, expect, it } from "vitest";
import { en } from "./en";
import { ru } from "./ru";
import { uk } from "./uk";

// Строки словаря плоско: «drawer.questions» → текст
function flat(o: object, prefix = ""): Map<string, string> {
  const out = new Map<string, string>();
  for (const [k, v] of Object.entries(o)) {
    if (typeof v === "string") out.set(prefix + k, v);
    else for (const [kk, vv] of flat(v as object, `${prefix}${k}.`)) out.set(kk, vv);
  }
  return out;
}
const vars = (s: string) => [...s.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort();

describe("словари интерфейса", () => {
  const base = flat(ru);
  for (const [name, dict] of [["uk", uk], ["en", en]] as const) {
    it(`${name}: те же ключи и подстановки, что в ru, без пустых строк`, () => {
      const other = flat(dict);
      expect([...other.keys()].sort()).toEqual([...base.keys()].sort());
      for (const [k, v] of base) {
        expect(vars(other.get(k)!), k).toEqual(vars(v));
        expect(other.get(k)!.trim(), k).not.toBe("");
      }
    });
  }
});
