// Flush boxes for the tests and the Storybook stories: the shape of the splice key of a point
// card (docs/epd-format.md, "objects"), after the examples of the format

import type { SpliceData, SpliceJoint } from "@/shared/types";

export const COLORS: Record<string, string> = { QF2: "#d4a72c", QF7: "#4e79a7", QF9: "#f28e2b" };

const joint = (conductor: SpliceJoint["conductor"], out: string[], over: Partial<SpliceJoint> = {}): SpliceJoint => ({
  conductor, wires: 1 + out.length + (over.taps ?? 1), out, taps: 1, clamps: ["413"], sleeves: 0, ...over,
});

// A socket of a loop: in, one cable on, every conductor joined with a tap to the socket
export const socketLoop = (over: Partial<SpliceData> = {}): SpliceData => ({
  method: "wago", deep_mm: 60,
  in: { key: "wire:wire_15", from: "Розетка із заземленням, Спальня", from_key: "point:bedroom_socket_4", group: "QF2", mark: "3x2.5", length_m: 7 },
  out: [{ key: "wire:wire_16", to: "Розетка із заземленням, Спальня", to_key: "point:bedroom_socket_2", kind: "point", point_type: "socket", number: 3, group: "QF2", mark: "3x2.5", length_m: 6.3 }],
  devices: 1,
  joints: ["L", "N", "PE"].map((c) => joint(c as SpliceJoint["conductor"], ["wire:wire_16"])),
  ...over,
});

// A switch: the phase goes on to the outlet with a tap to the switch; the lights get the switched
// wire from its terminals, their neutral and earth are joined
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

// Crimp sleeves instead of clamps, two devices in one frame
export const crimped = (): SpliceData => socketLoop({
  method: "crimp", devices: 2,
  joints: ["L", "N", "PE"].map((c) => joint(c as SpliceJoint["conductor"], ["wire:wire_16"], { taps: 2, clamps: [], sleeves: 1 })),
});
