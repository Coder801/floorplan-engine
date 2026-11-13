// "What's new" for users (widgets/Changelog): releases from the repository's CHANGELOG.md, which
// `cz bump` writes from commit titles (docs/development.md, "Commits and versions"). The file is
// read at build time (vite.config.ts, __CHANGELOG__). Only the list of changes goes to the page:
// scopes are dropped, refactors and purely internal entries (agents, docs, tests, deploy, admin)
// are left out. Client projects are never named in commit titles (committer agent); the test
// next to this file checks CHANGELOG.md against the folders in projects/.

declare const __CHANGELOG__: string;

export type ChangeKind = "added" | "improved" | "fixed" | "changed";
export const CHANGE_KINDS: ChangeKind[] = ["added", "improved", "fixed", "changed"];

export interface Release {
  version: string;
  date: string | null;  // YYYY-MM-DD
  changes: Partial<Record<ChangeKind, string[]>>;
}

// commitizen section headings → what the user reads
const KINDS: Record<string, ChangeKind> = { feat: "added", perf: "improved", fix: "fixed", "breaking change": "changed" };
// Scopes of work users do not see; an entry is hidden when all its scopes are here
const INTERNAL = new Set(["agents", "docs", "tests", "deploy", "admin", "ci", "build"]);

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function parseChangelog(md: string): Release[] {
  const out: Release[] = [];
  let release: Release | null = null;
  let kind: ChangeKind | null = null;
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    const head = /^##\s+v?(\d[\w.-]*)(?:\s*\((\d{4}-\d{2}-\d{2})\))?/.exec(line);
    if (head && !line.startsWith("###")) {
      release = { version: head[1], date: head[2] ?? null, changes: {} };
      out.push(release);
      kind = null;
      continue;
    }
    const section = /^###\s+(.+)$/.exec(line);
    if (section) { kind = KINDS[section[1].toLowerCase()] ?? null; continue; }
    const item = /^[-*]\s+(?:\*\*([^*]+)\*\*:\s*)?(.+)$/.exec(line);
    if (!item || !release || !kind) continue;
    const scopes = item[1]?.split(",").map((s) => s.trim()).filter(Boolean) ?? [];
    if (scopes.length && scopes.every((s) => INTERNAL.has(s))) continue;
    (release.changes[kind] ??= []).push(capital(item[2]));
  }
  return out.filter((r) => CHANGE_KINDS.some((k) => r.changes[k]?.length));
}

export const RELEASES: Release[] = parseChangelog(typeof __CHANGELOG__ === "string" ? __CHANGELOG__ : "");
