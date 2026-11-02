// Строки таблицы «На стене» по разделам: электрика — точки по номерам листа электрики,
// коробки и щит; вода — водорозетки и выпуски по номерам листа «Сантехника» (холодная,
// горячая, канализация). Подписи — снаружи (переводы), здесь только сборка.

import type { Elevation, PipeKind } from "@/shared/types";

export interface Row {
  id: string;            // ключ строки React: у прибора несколько подводов
  key: string;           // объект развёртки (подсветка): point:…, box:…, fixture:…
  mark: string;          // номер точки или прибора, «К3», «ЩР»
  color: string | null;  // плашка номера — цвет группы или сети
  name: string;
  where: string;         // отступ × высота, мм
  line: string | null;   // «QF4 · от К3» или «Холодная вода · Ø16»
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
