import { describe, expect, it } from "vitest";
import type { Scene, SceneHeating } from "@/shared/types";
import { heatingFeed } from "./heating";

const zone = (thermostat: string, wires: string[], boxes: string[]): SceneHeating => ({
  key: `heating:${thermostat}`, room: "bath", thermostat, area: [], cable: [], lead: [], sensor: [],
  feed: { wires, boxes },
  colors: { tint: "#ff9933", frame: "#d32f2f", cable: "#ef7b7b", lead: "#0000ff", sensor: "#9c27b0" },
});

const scene = (heating?: Record<string, SceneHeating>) =>
  ({ ceiling: 2700, assumed: { ceiling: false, openings: [] }, floors: [], walls: [], wires: {}, points: {},
     boxes: {}, heating }) as Scene;

describe("heatingFeed", () => {
  it("gives the controllers and the lines and boxes that feed them", () => {
    const keys = heatingFeed(scene({ a: zone("reg_a", ["wire_1", "wire_2"], ["box_1"]), b: zone("reg_b", ["wire_9"], []) }));
    expect([...keys].sort()).toEqual(["box:box_1", "point:reg_a", "point:reg_b", "wire:wire_1", "wire:wire_2", "wire:wire_9"]);
  });

  it("is empty without zones (a scene built before them)", () => {
    expect(heatingFeed(scene()).size).toBe(0);
  });
});
