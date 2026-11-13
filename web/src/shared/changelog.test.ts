import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseChangelog } from "./changelog";

const ROOT = join(__dirname, "..", "..", "..");

const SAMPLE = `## v0.7.0 (2026-11-13)

### Feat

- **viewer**: draw an engineering grid under the sheets
- **viewer,agents**: add ui atoms
- **agents,docs**: teach the committer
- plain entry without a scope

### Fix

- **electrical**: use 4x1.5 between pass switches

### Refactor

- **drawing**: split a long function

## v0.6.1 (2026-11-12)

### Refactor

- **core**: only internal work

## v0.6.0 (2026-11-12)

### Perf

- **electrical**: faster routing
`;

describe("parseChangelog", () => {
  it("версии с датами, разделы для пользователя, без области", () => {
    const r = parseChangelog(SAMPLE);
    expect(r.map((x) => x.version)).toEqual(["0.7.0", "0.6.0"]);
    expect(r[0].date).toBe("2026-11-13");
    expect(r[0].changes.added).toEqual(["Draw an engineering grid under the sheets", "Add ui atoms", "Plain entry without a scope"]);
    expect(r[0].changes.fixed).toEqual(["Use 4x1.5 between pass switches"]);
    expect(r[1].changes.improved).toEqual(["Faster routing"]);
  });

  it("рефакторинг и чисто внутренние записи не показываются", () => {
    const text = JSON.stringify(parseChangelog(SAMPLE));
    expect(text).not.toContain("teach the committer");
    expect(text).not.toContain("long function");
    expect(text).not.toContain("0.6.1");
  });

  it("пустой файл — пустой список", () => {
    expect(parseChangelog("")).toEqual([]);
  });
});

// The page is public to every user: client projects must not be named in it (and so not in commit
// titles, which cz bump copies into CHANGELOG.md)
describe("CHANGELOG.md", () => {
  const file = join(ROOT, "CHANGELOG.md");
  const projects = join(ROOT, "projects");
  it.skipIf(!existsSync(file))("разбирается: у каждой версии есть изменения", () => {
    const releases = parseChangelog(readFileSync(file, "utf8"));
    expect(releases.length).toBeGreaterThan(0);
    for (const r of releases) expect(Object.values(r.changes).flat().length, r.version).toBeGreaterThan(0);
  });

  it.skipIf(!existsSync(file) || !existsSync(projects))("не называет проекты из projects/", () => {
    const text = readFileSync(file, "utf8").toLowerCase();
    const names = readdirSync(projects).filter((n) => statSync(join(projects, n)).isDirectory() && !n.startsWith("."));
    // the name and its stem without the flat number (dacha-kitchen-2 → dacha)
    const stems = new Set(names.flatMap((n) => [n.toLowerCase(), n.toLowerCase().split(/[-_\d]/)[0]]).filter((s) => s.length >= 4));
    expect([...stems].filter((s) => text.includes(s))).toEqual([]);
  });
});
