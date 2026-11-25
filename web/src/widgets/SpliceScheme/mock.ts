// Flush boxes for the tests and the Storybook stories: the shape of the splice key of a point
// card (docs/epd-format.md, "objects"), after the examples of the format. Only switches of lights
// in a chain have joints (decision 2026-11-25): looped sockets use jumpers through their double
// terminals, so there is no socket example

import type { SpliceData, SpliceJoint } from "@/shared/types";

export const COLORS: Record<string, string> = { QF2: "#d4a72c", QF7: "#4e79a7", QF9: "#f28e2b" };

const joint = (conductor: SpliceJoint["conductor"], out: string[], over: Partial<SpliceJoint> = {}): SpliceJoint => ({
  conductor, wires: 1 + out.length + (over.taps ?? 1), out, taps: 1, clamps: ["413"], sleeves: 0, ...over,
});

// A switch (the example of docs/epd-format.md, key splice): the phase goes on to the outlet with
// a tap to the switch; the lights get the switched wire from its terminals, their neutral and
// earth are joined
export const hallSwitch = (over: Partial<SpliceData> = {}): SpliceData => ({
  method: "wago", deep_mm: 60,
  in: { key: "wire:wire_42", from: "ЩР", from_key: "board", group: "QF7", mark: "3x1.5", length_m: 9.8 },
  out: [
    { key: "wire:wire_39", to: "Світильник точковий, Гардеробна", to_key: "point:wardrobe_downlight_3", kind: "point", point_type: "downlight", number: 52, group: "QF7", mark: "4x1.5", length_m: 4 },
    { key: "wire:wire_43", to: "Вивід кабелю до техніки, Гардеробна", to_key: "point:wardrobe_outlet_1", kind: "point", point_type: "outlet", number: 49, group: "QF7", mark: "3x1.5", length_m: 3.7 },
  ],
  devices: 1,
  joints: [
    joint("L", ["wire:wire_43"]),
    joint("N", ["wire:wire_39", "wire:wire_43"], { taps: 0 }),
    joint("PE", ["wire:wire_39", "wire:wire_43"], { taps: 0 }),
  ],
  ...over,
});

// A pass switch: only neutral and earth pass through, two wires each
export const passSwitch = (over: Partial<SpliceData> = {}): SpliceData => ({
  method: "wago", deep_mm: 60,
  in: { key: "wire:wire_1", from: "Вимикач прохідний, Спальня", from_key: "point:bedroom_pass_switch_1", group: "QF9", mark: "5x1.5", length_m: 3.2 },
  out: [{ key: "wire:wire_2", to: "Світильник, Спальня", to_key: "point:bedroom_light_1", kind: "point", point_type: "light", number: 61, group: "QF9", mark: "3x1.5", length_m: 2.1 }],
  devices: 1,
  joints: [joint("N", ["wire:wire_2"], { taps: 0, clamps: ["412"] }), joint("PE", ["wire:wire_2"], { taps: 0, clamps: ["412"] })],
  ...over,
});

// Crimp sleeves instead of clamps, a two-gang switch: the phase has a tap to each of its keys
export const crimped = (): SpliceData => hallSwitch({
  method: "crimp", devices: 2,
  joints: [
    joint("L", ["wire:wire_43"], { taps: 2, clamps: [], sleeves: 1 }),
    joint("N", ["wire:wire_39", "wire:wire_43"], { taps: 0, clamps: [], sleeves: 1 }),
    joint("PE", ["wire:wire_39", "wire:wire_43"], { taps: 0, clamps: [], sleeves: 1 }),
  ],
});
