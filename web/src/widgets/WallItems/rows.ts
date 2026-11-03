// Rows of the "On the wall" table by section: electrical has points by electrical sheet number,
// boxes and the panel; water has water outlets and drains by "Plumbing" sheet number (cold,
// hot, sewer). Labels come from outside (translations); this only assembles the rows.

import type { Elevation, PipeKind } from "@/shared/types";

export interface Row {
  id: string;            // React row key: a fixture has several supplies
  key: string;           // elevation object (highlight): point:…, box:…, fixture:…
  mark: string;          // point or fixture number, "К3", "ЩР"
  color: string | null;  // number badge: group or network colour
  name: string;
  where: string;         // offset × height, mm
  line: string | null;   // "QF4 · от К3" or "Холодная вода · Ø16"
  box?: boolean;
}

export interface Labels {
  from: (from: string) => string;
  box: string;
  board: string;
  kind: Record<PipeKind, string>;
}

const KIND_ORDER: Record<PipeKind, number> = { cold: 0, hot: 1, sewer: 2 };
const mm = (x: number, y: number) => `${Math.round(x)} × ${Math.round(y)}`;
const joined = (...xs: (string | null | undefined)[]) => xs.filter(Boolean).join(" · ") || null;

export function wallRows(wall: Elevation, l: Labels, colors: Record<PipeKind, string>) {
  const via = (f: string | null) => (f ? l.from(f) : null);
  const electrical: Row[] = [
    ...wall.points.map((p) => ({
      id: p.key, key: p.key, mark: String(p.n), color: p.color, name: p.name, where: mm(p.x, p.y),
      line: joined(p.group, via(p.from)),
    })),
    ...wall.boxes.map((b) => ({
      id: b.key, key: b.key, mark: b.label, color: null, name: l.box, where: mm(b.x, b.y),
      line: joined(b.group, via(b.from)), box: true,
    })),
    ...(wall.board ? [{ id: wall.board.key, key: wall.board.key, mark: wall.board.name, color: null,
                        name: l.board, where: mm(wall.board.x, wall.board.y), line: null }] : []),
  ];
  const water: Row[] = [...(wall.water ?? [])]
    .sort((a, b) => a.n - b.n || KIND_ORDER[a.kind] - KIND_ORDER[b.kind])
    .map((v) => ({
      id: `${v.key}.${v.kind}`, key: v.key, mark: `${v.n}${v.assumed ? "*" : ""}`,
      color: colors[v.kind], name: v.name, where: mm(v.x, v.y), line: joined(l.kind[v.kind], `Ø${v.d}`),
    }));
  return { electrical, water };
}
