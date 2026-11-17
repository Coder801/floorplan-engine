// The lines of a ceiling (floor) view as an installer reads them (decision 2026-11-17): by panel
// group, each group as its chain — the feed from the panel, then box by box the lines that leave
// it, the line to the next box last. Ends are matched by id (source / target of the build); an
// older .epd without them falls back to the names.

import type { CeilingLine } from "@/shared/types";

// A row of an open group: a node (box, panel, chain point) the lines below leave from, or a line.
// tail: the last line of its node ("└"); next: the line goes on to the next node of the chain
export type ChainRow =
  | { kind: "node"; id: string; name: string; keys: string[] }
  | { kind: "line"; line: CeilingLine; branch: boolean; tail: boolean; next: boolean };

export interface LineGroup {
  group: string;
  color: string | null;
  marks: string[];        // cables of the group, in order
  lines: CeilingLine[];   // wiring order
  keys: string[];         // lanes of the group on the view
  length: number;         // in the room, mm
  transit: boolean;       // every line only passes through the room
  rows: ChainRow[];
}

const src = (ln: CeilingLine) => ln.source ?? ln.from;
const dst = (ln: CeilingLine) => ln.target ?? ln.to;

// The chain of one group: blocks node → its lines in depth-first order from the nodes no line of
// the group comes into (the panel, or a box fed from outside the room). A node with one line and
// no line into it is that line alone ("ЩР → К1"); otherwise a node row and its lines under it,
// the ones going on to a node of the chain last
export function chainRows(lines: CeilingLine[]): ChainRow[] {
  const out: ChainRow[] = [];
  const from = new Map<string, CeilingLine[]>();
  for (const ln of lines) from.set(src(ln), [...(from.get(src(ln)) ?? []), ln]);
  const fed = new Set(lines.map(dst));
  const seen = new Set<string>();
  const block = (node: string) => {
    if (seen.has(node)) return;
    seen.add(node);
    const own = from.get(node) ?? [];
    const goesOn = (ln: CeilingLine) => from.has(dst(ln)) && !seen.has(dst(ln));
    const ordered = [...own.filter((ln) => !goesOn(ln)), ...own.filter(goesOn)];
    const alone = ordered.length === 1 && !fed.has(node);
    if (!alone) out.push({ kind: "node", id: node, name: own[0].from, keys: own.map((ln) => ln.key) });
    ordered.forEach((ln, i) => out.push({
      kind: "line", line: ln, branch: !alone, tail: i === ordered.length - 1, next: !alone && goesOn(ln),
    }));
    for (const ln of ordered) if (from.has(dst(ln))) block(dst(ln));
  };
  for (const ln of lines) if (!fed.has(src(ln))) block(src(ln));
  // A loop without a start (should not happen): its nodes in wiring order
  for (const ln of lines) block(src(ln));
  return out;
}

// Groups in panel order (as the lines come, wiring order follows the panel); groups whose every
// line only passes through the room go last
export function lineGroups(lines: CeilingLine[]): LineGroup[] {
  const by = new Map<string, CeilingLine[]>();
  for (const ln of lines) by.set(ln.group, [...(by.get(ln.group) ?? []), ln]);
  const groups = [...by].map(([group, of]): LineGroup => ({
    group,
    color: of.find((ln) => ln.color)?.color ?? null,
    marks: [...new Set(of.map((ln) => ln.mark))],
    lines: of,
    keys: of.map((ln) => ln.key),
    length: of.reduce((s, ln) => s + ln.length, 0),
    transit: of.every((ln) => ln.transit === true),
    rows: chainRows(of),
  }));
  return [...groups.filter((g) => !g.transit), ...groups.filter((g) => g.transit)];
}

// Cable in the room by mark, in order of first use: [["3x1.5", 38400], …], mm
export function cableTotals(lines: CeilingLine[]): [string, number][] {
  const sums = new Map<string, number>();
  for (const ln of lines) sums.set(ln.mark, (sums.get(ln.mark) ?? 0) + ln.length);
  return [...sums];
}

// The route of a line along its group chain: the names from the start of the chain to its end
// ("ЩР → К1 → К2 → 12 · Выключатель")
export function routeTo(lines: CeilingLine[], line: CeilingLine): string[] {
  const into = new Map(lines.map((ln) => [dst(ln), ln]));
  const names = [line.to, line.from];
  const seen = new Set([dst(line)]);
  for (let at = into.get(src(line)); at && !seen.has(dst(at)); at = into.get(src(at))) {
    seen.add(dst(at));
    names.push(at.from);
  }
  return names.reverse();
}
