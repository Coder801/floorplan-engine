// Junction boxes for the tests and the Storybook stories: the shape of the box key of a box card
// (docs/epd-format.md, "objects")

import type { BoxBranch, BoxData } from "@/shared/types";

export const COLORS: Record<string, string> = { QF1: "#f28e2b", QF2: "#d4a72c", QF5: "#4e79a7" };

const POINTS: [string, string, number][] = [
  ["Вимикач, Коридор", "switch", 3], ["Світильник, Коридор", "light", 4], ["Розетка, Зал", "socket", 5],
  ["Розетка подвійна, Зал", "socket", 6], ["Світильник, Зал", "light", 7], ["Вимикач прохідний, Зал", "pass_switch", 8],
  ["LED-стрічка, Зал", "led_strip", 9], ["Розетка, Балкон", "socket", 10],
];

export const branch = (i: number, over: Partial<BoxBranch> = {}): BoxBranch => {
  const [to, type, n] = POINTS[i % POINTS.length];
  return {
    key: `wire:wire_${i + 2}`, to, to_key: `point:p${n}`, kind: "point", point_type: type, number: n,
    group: "QF1", mark: "3x1.5", length_m: 1.6 + i * 0.7, ...over,
  };
};

export const boxData = (over: Partial<BoxData> = {}): BoxData => ({
  label: "К1", size: "100×100",
  in: { key: "wire:wire_1", from: "ЩР", from_key: "board", group: "QF1", mark: "3x1.5", length_m: 3.9 },
  out: [
    branch(0),
    branch(1),
    { key: "wire:wire_9", to: "К2", to_key: "box:box_2", kind: "box", point_type: null, number: null, group: "QF1", mark: "3x1.5", length_m: 2.4 },
    branch(2, { group: "QF5", mark: "3x2.5" }),
  ],
  ...over,
});

// Ten cables out: the upper end of what the card is laid out for
export const manyOuts = (): BoxData => boxData({ out: Array.from({ length: 10 }, (_, i) => branch(i, i === 7 ? { number: null } : {})) });
