// Раскладка src по группам (web/README.md, «Устройство»): компонент — папка ИмяКомпонента/
// с index.tsx и ИмяКомпонента.module.scss; группа импортирует только разрешённые группы.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname);
const GROUPS = ["pages", "widgets", "ui", "engine", "shared"] as const;
type Group = (typeof GROUPS)[number];
const COMPONENT_GROUPS: Group[] = ["pages", "widgets", "ui"];

// Кого можно импортировать из группы
const ALLOWED: Record<Group, Group[]> = {
  pages: ["pages", "widgets", "ui", "engine", "shared"],
  widgets: ["widgets", "ui", "engine", "shared"],
  ui: ["shared"],
  engine: ["engine", "shared"],
  shared: ["shared"],
};

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : [p];
  });
}
const code = files(SRC).filter((f) => /\.tsx?$/.test(f) && !f.endsWith(".d.ts"));

describe("раскладка src", () => {
  it("в корне — только точка входа, остальное — по группам", () => {
    const top = readdirSync(SRC).filter((f) => !f.endsWith(".test.ts"));
    expect(top.sort()).toEqual([...GROUPS, "main.tsx"].sort());
  });

  for (const group of COMPONENT_GROUPS) {
    it(`${group}: компонент — папка с index.tsx и стилями по имени папки`, () => {
      for (const name of readdirSync(join(SRC, group))) {
        const dir = join(SRC, group, name);
        expect(statSync(dir).isDirectory(), `${group}/${name} — не папка`).toBe(true);
        expect(name, `${group}/${name}: имя папки — ИмяКомпонента`).toMatch(/^[A-Z][A-Za-z0-9]*$/);
        const inside = readdirSync(dir).filter((f) => !f.endsWith(".d.ts"));
        expect(inside, `${group}/${name}: нет index.tsx`).toContain("index.tsx");
        for (const f of inside.filter((f) => f.endsWith(".module.scss"))) {
          expect(f, `${group}/${name}: стили — ${name}.module.scss`).toBe(`${name}.module.scss`);
        }
      }
    });
  }

  it("группы импортируют только разрешённые группы", () => {
    const bad: string[] = [];
    for (const f of code) {
      const from = relative(SRC, f).split("/")[0] as Group;
      if (!GROUPS.includes(from)) continue;
      for (const m of readFileSync(f, "utf8").matchAll(/(?:from|import)\s*\(?\s*"@\/([a-z]+)\//g)) {
        if (!ALLOWED[from].includes(m[1] as Group)) bad.push(`${relative(SRC, f)} → @/${m[1]}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("между группами — через алиас @/, без ../", () => {
    const bad = code.filter((f) => /from\s+"\.\.\//.test(readFileSync(f, "utf8"))).map((f) => relative(SRC, f));
    expect(bad).toEqual([]);
  });
});
