import { describe, expect, it } from "vitest";
import { clampModels, jointCables, offTerminals } from "./joints";
import { hallSwitch, passSwitch } from "./mock";

describe("соединения подрозетника", () => {
  it("выключатель: кабель к светильникам не в фазе — с клемм механизма, к технике — по фазе", () => {
    expect(offTerminals(hallSwitch())).toEqual(new Set(["wire:wire_39"]));
  });
  it("все кабели в соединении фазы — с клемм ни одного", () => {
    const s = hallSwitch();
    expect(offTerminals({ ...s, joints: [{ ...s.joints[0], out: ["wire:wire_39", "wire:wire_43"] }] })).toEqual(new Set());
  });
  it("проходной: фаза не соединяется — дальше всё с клемм", () => {
    expect(offTerminals(passSwitch())).toEqual(new Set(["wire:wire_2"]));
  });
  it("клеммы одной строкой, две — с плюсом; гильза — пусто", () => {
    const j = hallSwitch().joints[0];
    expect(clampModels(j)).toBe("413");
    expect(clampModels({ ...j, clamps: ["415", "413"] })).toBe("415 + 413");
    expect(clampModels({ ...j, clamps: [] })).toBe("");
  });
  it("в соединении всегда есть ввод, без ввода — только кабели из него", () => {
    const s = hallSwitch();
    expect(jointCables(s, s.joints[1])).toEqual(["wire:wire_42", "wire:wire_39", "wire:wire_43"]);
    expect(jointCables({ ...s, in: null }, s.joints[0])).toEqual(["wire:wire_43"]);
  });
});
