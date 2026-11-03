import { describe, expect, it } from "vitest";
import {
  groupOf, keepOrder, listOrder, nextOpen, objectOf, parseNumber, plainNumber, shortMessage, shownOn, statusOf,
} from "./questions";
import type { Question } from "./types";

const q = (id: string, state = "open", severity = "major"): Question =>
  ({ id, state, severity, stage: "plan", text: id, answer: "value" });

describe("вопросы", () => {
  it("состояние — по ответу: текст не пересобирает проект, отчёт отстаёт", () => {
    expect(statusOf(undefined)).toBe("open");
    expect(statusOf({ text: "т" })).toBe("pending");
    expect(statusOf({ text: "т", resolved: true })).toBe("resolved");
    expect(statusOf({ accept: true })).toBe("accepted");
    expect(statusOf(700)).toBe("answered");
    expect(statusOf(0)).toBe("answered");
    expect(groupOf("resolved")).toBe("closed");
  });

  it("порядок: группы, внутри — вес", () => {
    const qs = [q("m"), q("done", "answered"), q("min", "open", "minor"), q("crit", "open", "critical"), q("p")];
    const order = listOrder(qs, { done: 700, p: { text: "т" } });
    expect([...order.keys()]).toEqual(["crit", "m", "min", "p", "done"]);
    expect(order.get("p")).toBe("pending");
  });

  it("порядок держится, пропавшие вопросы уходят, новые — к нужным ответа", () => {
    const order = listOrder([q("a"), q("b")], {});
    const kept = keepOrder(order, [q("b"), q("c")]);
    expect([...kept]).toEqual([["b", "open"], ["c", "open"]]);
  });

  it("следующий без ответа — дальше по списку, потом с начала", () => {
    const st = (id: string) => (id === "b" ? "answered" : "open");
    expect(nextOpen(["a", "b", "c"], st, "b")).toBe("c");
    expect(nextOpen(["a", "b", "c"], st, "c")).toBe("a");
    expect(nextOpen(["a"], st, "a")).toBeNull();
    expect(nextOpen(["b"], st, "b")).toBeNull();
  });

  it("число: запятая и пробелы", () => {
    expect(parseNumber(" 1 783,5 ")).toBe(1783.5);
    expect(parseNumber("много")).toBeNull();
    expect(parseNumber(" ")).toBeNull();
    expect(plainNumber(700.0)).toBe("700");
    expect(plainNumber("48.0")).toBe("48");
  });

  it("сообщение для заказчика — первая фраза", () => {
    expect(shortMessage("контур не замыкается: 117 мм. Замкнётся, если исправить стену")).toBe("контур не замыкается: 117 мм");
  });

  it("поле вопроса → объект на листе", () => {
    expect(objectOf("points.kitchen_socket_1.height")).toBe("point:kitchen_socket_1");
    expect(objectOf("rooms.kitchen.openings.kitchen_door_1.width")).toBe("opening:kitchen_door_1");
    expect(objectOf("rooms.kitchen.walls.w3.length")).toBe("wall:kitchen.w3");
    expect(objectOf("rooms.kitchen.ceiling_height")).toBe("room:kitchen");
    expect(objectOf("board.offset")).toBe("board:board");
    expect(objectOf("risers.r1.at")).toBe("riser:r1");
    expect(objectOf("default_wall_thickness")).toBeNull();
    expect(objectOf("boards")).toBeNull();
    expect(objectOf(undefined)).toBeNull();
  });

  it("куда ведёт «показать»: объект своего этапа, вопрос щита — вкладка без объекта", () => {
    const stages = ["plan", "electrical", "panel"];
    expect(shownOn({ ...q("a"), stage: "electrical", target: "points.p1.height" }, stages))
      .toEqual({ stage: "electrical", key: "point:p1" });
    expect(shownOn({ ...q("a"), stage: "panel", target: "panel.backup" }, stages)).toEqual({ stage: "panel", key: null });
    expect(shownOn({ ...q("a"), stage: "panel" }, ["plan"])).toBeNull();
    expect(shownOn({ ...q("a"), stage: "plan" }, stages)).toBeNull();
    expect(shownOn({ ...q("a"), stage: "plumbing", target: "risers.r1.at" }, stages)).toBeNull();
  });
});
