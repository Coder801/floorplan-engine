import { describe, expect, it } from "vitest";
import type { Question, Variants, VariantSummary } from "@/shared/types";
import { ART } from "@/widgets/WizardArt";
import { UNKNOWN, applyPick, chasesKept, initialPicks, invalid, otherQuestions, setupProgress, variantOf, wizardBody, wizardSteps, type Picks, type Setup, type Step } from "./steps";

const q = (id: string, assumption: unknown, state = "open"): Question =>
  ({ id, stage: "panel", severity: "major", state, text: id, answer: "choice", assumption });

const item = (mode: string, route: string) =>
  ({ key: `${mode}-${route}-boxes`, mode, route, distribution: "boxes" }) as VariantSummary;
const variants: Variants = {
  active: "standard-ceiling-boxes", default: "standard-ceiling-boxes",
  items: ["economy", "standard", "proper"].flatMap((m) => [item(m, "ceiling"), item(m, "floor")]),
};
const dc = [q("panel_inverter", "hybrid"), q("panel_battery", 48), q("panel_pv", 0), q("panel_npe", "yes")];

function setup(over: Partial<Setup> = {}): Setup {
  return {
    questions: [q("panel_input", 63), q("panel_backup", "inverter"), ...dc],
    answers: {}, variants, ceiling: 2700, reserve: null, canChoose: true, canAnswer: true, ...over,
  };
}
const ids = (s: Setup, picks = initialPicks(s)) => wizardSteps(s, picks).map((x) => x.id);
const WIRING = ["route", "distribution", "path", "conduit", "plaster", "ceiling", "rough"];
const yes = (picks: Picks): Picks => ({ ...picks, standby: "yes" });

describe("шаги мастера", () => {
  it("уровня проводки нет: каждый пункт — свой шаг; про резерв — только закладка", () => {
    expect(ids(setup())).toEqual([...WIRING, "input", "breakers", "standby"]);
  });
  it("закладка «да» открывает резерв, «нет» и без ответа — закрывает", () => {
    const s = setup();
    expect(ids(s, yes({}))).toEqual([...WIRING, "input", "breakers", "standby", "backup", "inverter", "battery", "pv", "npe"]);
    expect(ids(s, { standby: "no", backup: "none" })).not.toContain("backup");
    expect(ids(s, {})).not.toContain("inverter");
  });
  it("щит и резерв — разные разделы: в резерве закладка и всё, что она открывает", () => {
    const steps = wizardSteps(setup(), yes({}));
    const of = (group: Step["group"]) => steps.filter((x) => x.group === group).map((x) => x.id);
    expect(of("panel")).toEqual(["input", "breakers"]);
    expect(of("reserve")).toEqual(["standby", "backup", "inverter", "battery", "pv", "npe"]);
  });
  it("без инвертора его шагов нет, с инвертором — появляются", () => {
    const s = setup();
    expect(ids(s, yes({ backup: "plug" }))).not.toContain("battery");
    expect(ids(s, yes({ backup: "inverter" }))).toContain("battery");
  });
  it("в выборе резерва нет «без резерва»: это ответ на закладку", () => {
    const steps = wizardSteps(setup(), yes({}));
    expect(steps.find((x) => x.id === "backup")?.options).toEqual(["inverter", "plug", "station", UNKNOWN]);
    expect(steps.find((x) => x.id === "standby")?.options).toEqual(["no", "yes"]);
  });
  it("резерв «нет» в ответах: вопросов инвертора нет в отчёте, но выбор их открывает", () => {
    const s = setup({ questions: [q("panel_backup", "inverter", "answered")], answers: { panel_backup: "none" } });
    expect(ids(s)).not.toContain("inverter");
    const steps = wizardSteps(s, yes({ backup: "inverter" }));
    expect(steps.find((x) => x.id === "inverter")?.question).toBeUndefined();
    expect(steps.map((x) => x.id)).toEqual(expect.arrayContaining(["inverter", "battery", "pv", "npe"]));
  });
  it("поле задано в YAML — шага нет", () => {
    const s = setup({ questions: [q("panel_backup", "inverter"), q("panel_inverter", "hybrid")] });
    expect(ids(s, yes({}))).toEqual([...WIRING, "breakers", "standby", "backup", "inverter"]);
  });
  it("резерв задан в YAML: шаги инвертора — по отчёту", () => {
    expect(ids(setup({ questions: dc }), {})).toEqual([...WIRING, "breakers", "inverter", "battery", "pv", "npe"]);
    expect(ids(setup({ questions: [] }), {})).toEqual([...WIRING, "breakers"]);
  });
  it("одна трасса в проекте — не спрашиваем", () => {
    const one = { ...variants, items: variants.items.filter((i) => i.route === "ceiling") };
    expect(ids(setup({ variants: one }))).not.toContain("route");
  });
  it("права: клиент студии только отвечает, монтажник только выбирает вариант", () => {
    expect(ids(setup({ canChoose: false }))[0]).toBe("input");
    expect(ids(setup({ canAnswer: false }))).toEqual([...WIRING, "breakers"]);
  });
  it("у каждой карточки есть иллюстрация", () => {
    const steps = wizardSteps(setup(), yes({ backup: "inverter" }));
    const names = steps.flatMap((s: Step) => (s.kind === "cards" ? s.options.map((o) => (o === UNKNOWN ? o : `${s.id}-${o}`)) : s.kind === "number" ? [s.id] : []));
    expect(names.filter((n) => !(n in ART))).toEqual([]);
  });
});

describe("шаг резерва", () => {
  const reserve = { limit_kw: 5, limit_assumed: true, items: [
    { id: "QF1", purpose: "Свет", power: 400, on: true }, { id: "QF2", purpose: "Розетки", power: 900, on: false },
  ] };
  const withQuestion = (over: Partial<Setup> = {}) =>
    setup({ questions: [...setup().questions, q("panel_reserve", undefined)], reserve, ...over });

  it("есть шина и вопрос — шаг в конце щита, группы из сборки", () => {
    const s = withQuestion();
    const steps = wizardSteps(s, yes(initialPicks(s)));
    expect(steps[steps.length - 1]).toMatchObject({ id: "reserve", options: ["QF1", "QF2"] });
  });
  it("нет шины в сборке, вопроса или выбрано «без резерва» — шага нет", () => {
    expect(ids(setup({ reserve }))).not.toContain("reserve");
    const none = withQuestion({ reserve: null });
    expect(ids(none, yes({ backup: "inverter" }))).not.toContain("reserve");
    expect(ids(withQuestion(), { standby: "no", backup: "none" })).not.toContain("reserve");
    expect(ids(withQuestion(), yes({ backup: "plug" }))).toContain("reserve");
  });
  it("выбор — списком, не открытый вопрос — не отправляется", () => {
    const s = withQuestion();
    expect(wizardBody(s, initialPicks(s))).toEqual({});
    expect(wizardBody(s, yes({ ...initialPicks(s), reserve: "QF1,QF2" })).answers).toEqual({ panel_reserve: ["QF1", "QF2"] });
  });
  it("прежний ответ читается и не уходит без изменений", () => {
    const s = withQuestion({ answers: { panel_reserve: ["QF2"] } });
    expect(initialPicks(s).reserve).toBe("QF2");
    expect(wizardBody(s, initialPicks(s))).toEqual({});
  });
  it("«без резерва» снимает ответ про шину, генератор — нет", () => {
    const s = withQuestion({ answers: { panel_reserve: ["QF2"] } });
    expect(wizardBody(s, applyPick(initialPicks(s), "standby", "no")).answers).toEqual({ panel_backup: "none", panel_reserve: null });
    expect(wizardBody(s, yes({ ...initialPicks(s), backup: "plug" })).answers).toEqual({ panel_backup: "plug" });
  });
});

describe("начальный выбор", () => {
  it("вариант, потолок и ответы; открытый вопрос не выбран за человека", () => {
    const s = setup({ answers: { panel_input: 40, panel_battery: { accept: true } } });
    expect(initialPicks(s)).toEqual({
      route: "ceiling", distribution: "boxes", path: "right", conduit: "plain", plaster: "after", rough: "no", breakers: "groups",
      ceiling: "2700", input: "40", battery: UNKNOWN,
    });
  });
  it("набор из активного варианта; старая сборка без опций — по режиму", () => {
    const own = { ...item("standard", "floor"), key: "standard-floor-loop-shortest-conduit", distribution: "loop", path: "shortest", conduit: true } as VariantSummary;
    const s = setup({ variants: { ...variants, active: own.key, items: [...variants.items, own] } });
    expect(initialPicks(s)).toMatchObject({ route: "floor", distribution: "loop", path: "shortest", conduit: "tube", breakers: "groups" });
    const old = setup({ variants: { ...variants, active: "economy-ceiling-boxes" } });
    expect(initialPicks(old)).toMatchObject({ path: "shortest", conduit: "plain", breakers: "simple" });
    const premium = setup({ variants: { ...variants, active: "proper-ceiling-boxes" } });
    expect(initialPicks(premium)).toMatchObject({ path: "right", conduit: "tube", breakers: "lines" });
  });
  it("закладка — из ответа про резерв, открытый вопрос без ответа", () => {
    expect(initialPicks(setup()).standby).toBeUndefined();
    expect(initialPicks(setup({ answers: { panel_backup: "none" } })).standby).toBe("no");
    expect(initialPicks(setup({ answers: { panel_backup: "plug" } })).standby).toBe("yes");
    expect(initialPicks(setup({ answers: { panel_backup: { accept: true } } })).standby).toBe("yes");
  });
});

describe("что уходит на сервер", () => {
  it("ничего не поменяли — пусто", () => {
    const s = setup({ answers: { panel_input: 40 } });
    expect(wizardBody(s, initialPicks(s))).toEqual({});
  });
  it("вариант целиком, высота — только если менялась", () => {
    const s = setup();
    expect(wizardBody(s, { ...initialPicks(s), route: "floor" }).variant)
      .toEqual({ mode: "standard", route: "floor", distribution: "boxes", path: "right", conduit: false, plaster: "after", rough_light: false });
    expect(wizardBody(s, { ...initialPicks(s), ceiling: "3000" }).variant)
      .toEqual({ mode: "standard", route: "ceiling", distribution: "boxes", path: "right", conduit: false, plaster: "after", rough_light: false, ceiling_height: 3000 });
  });
  it("каждый пункт меняет вариант", () => {
    const s = setup();
    const with_ = (id: "distribution" | "path" | "conduit", value: string) => wizardBody(s, { ...initialPicks(s), [id]: value }).variant;
    expect(with_("distribution", "loop")?.distribution).toBe("loop");
    expect(with_("path", "shortest")?.path).toBe("shortest");
    expect(with_("conduit", "tube")?.conduit).toBe(true);
    const job = (id: "plaster" | "rough", value: string) => wizardBody(s, { ...initialPicks(s), [id]: value }).variant;
    expect(job("plaster", "before")?.plaster).toBe("before");
    expect(job("rough", "yes")?.rough_light).toBe(true);
  });
  it("автоматы: «как в премиуме» — режим премиум, обратно — стандарт, эконом остаётся экономом", () => {
    const s = setup();
    expect(wizardBody(s, { ...initialPicks(s), breakers: "lines" }).variant?.mode).toBe("proper");
    const premium = setup({ variants: { ...variants, active: "proper-ceiling-boxes" } });
    expect(wizardBody(premium, { ...initialPicks(premium), breakers: "groups" }).variant?.mode).toBe("standard");
    const economy = setup({ variants: { ...variants, active: "economy-ceiling-boxes" } });
    expect(variantOf(economy, initialPicks(economy)).mode).toBe("economy");
    expect(wizardBody(s, { ...initialPicks(s), breakers: "simple" }).variant?.mode).toBe("economy");
    expect(wizardBody(economy, { ...initialPicks(economy), breakers: "groups" }).variant?.mode).toBe("standard");
  });
  it("числа — числами, выбор — строкой", () => {
    const s = setup();
    const picks = yes({ ...initialPicks(s), input: "40", backup: "inverter", battery: "24", pv: "2", npe: "no" });
    expect(wizardBody(s, picks).answers).toEqual({
      panel_input: 40, panel_backup: "inverter", panel_battery: 24, panel_pv: 2, panel_npe: "no",
    });
  });
  it("ушли от инвертора — его ответы снимаются вместе с ним", () => {
    const s = setup({ answers: { panel_backup: "inverter", panel_battery: 24 } });
    expect(wizardBody(s, applyPick(initialPicks(s), "standby", "no")).answers)
      .toEqual({ panel_backup: "none", panel_battery: null });
  });
  it("закладка «нет» — ответ «без резерва», «да» после него снимает ответ", () => {
    const s = setup();
    const no = applyPick(initialPicks(s), "standby", "no");
    expect(no).toMatchObject({ standby: "no", backup: "none" });
    expect(wizardBody(s, no).answers).toEqual({ panel_backup: "none" });
    const was = setup({ answers: { panel_backup: "none" } });
    const back = applyPick(initialPicks(was), "standby", "yes");
    expect(back.backup).toBeUndefined();
    expect(wizardBody(was, back).answers).toEqual({ panel_backup: null });
    expect(wizardBody(was, { ...back, backup: "plug" }).answers).toEqual({ panel_backup: "plug" });
  });
  it("«да» не сбрасывает уже выбранный резерв", () => {
    expect(applyPick({ backup: "plug" }, "standby", "yes")).toEqual({ standby: "yes", backup: "plug" });
  });
  it("без права на вариант вариант не уходит", () => {
    const s = setup({ canChoose: false });
    expect(wizardBody(s, { ...initialPicks(s), path: "shortest" }).variant).toBeUndefined();
  });
});

describe("не знаю", () => {
  it("есть на каждой карточке вопроса, но не у варианта проводки", () => {
    const s = setup();
    const steps = wizardSteps(s, yes(initialPicks(s)));
    expect(steps.find((x) => x.id === "battery")?.options).toContain(UNKNOWN);
    expect(steps.find((x) => x.id === "path")?.options).not.toContain(UNKNOWN);
    expect(steps.find((x) => x.id === "standby")?.options).not.toContain(UNKNOWN);
  });
  it("уходит как «оставить» и закрывает шаг", () => {
    const s = setup();
    const picks = yes({ ...initialPicks(s), input: UNKNOWN, battery: UNKNOWN });
    expect(wizardBody(s, picks).answers).toEqual({ panel_input: { accept: true }, panel_battery: { accept: true } });
    expect(invalid({ id: "input", kind: "number" } as Step, UNKNOWN)).toBe(false);
    const answers = { panel_input: { accept: true }, panel_backup: "none" };
    expect(setupProgress(setup({ answers })).open).toEqual([]);
  });
  it("«не знаю» про резерв — допущение: шаги инвертора остаются, сохранённый ответ не дублируется", () => {
    const s = setup({ answers: { panel_backup: { accept: true } } });
    expect(initialPicks(s).backup).toBe(UNKNOWN);
    expect(ids(s)).toContain("battery");
    expect(wizardBody(s, initialPicks(s))).toEqual({});
  });
  it("«не знаю» после «без резерва» возвращает шаги инвертора", () => {
    const s = setup({ questions: [q("panel_backup", "inverter", "answered")], answers: { panel_backup: "none" } });
    expect(ids(s, yes({ backup: UNKNOWN }))).toContain("inverter");
  });
  it("станция — как генератор: шагов инвертора нет, его ответы снимаются", () => {
    const s = setup({ answers: { panel_backup: "inverter", panel_battery: 24 } });
    expect(ids(s, yes({ backup: "station" }))).not.toContain("battery");
    expect(wizardBody(s, yes({ ...initialPicks(s), backup: "station" })).answers).toEqual({ panel_backup: "station", panel_battery: null });
  });
});

describe("штробы при монтаже до штукатурки", () => {
  it("с гофрой на потолке — все, по полу — линии пола, без гофры и после штукатурки — ничего", () => {
    expect(chasesKept({ plaster: "before", conduit: "tube", route: "ceiling" })).toBe("all");
    expect(chasesKept({ plaster: "before", conduit: "tube", route: "floor" })).toBe("all");
    expect(chasesKept({ plaster: "before", conduit: "plain", route: "floor" })).toBe("floor");
    expect(chasesKept({ plaster: "before", conduit: "plain", route: "ceiling" })).toBeNull();
    expect(chasesKept({ plaster: "after", conduit: "tube", route: "floor" })).toBeNull();
  });
});

describe("сколько осталось решить", () => {
  it("открытые вопросы; вариант и потолок уже со значением", () => {
    expect(setupProgress(setup())).toEqual({ total: 10, open: ["input", "standby"] });
  });
  it("ответ, «оставить» и резерв без инвертора закрывают шаги", () => {
    const answers = { panel_input: 40, panel_backup: "none" };
    expect(setupProgress(setup({ answers })).open).toEqual([]);
    expect(setupProgress(setup({ answers: { ...answers, panel_input: { accept: true } } })).open).toEqual([]);
  });
});

describe("проверки", () => {
  const ceiling = { id: "ceiling", kind: "number" } as Step;
  const input = { id: "input", kind: "number" } as Step;
  it("высота и автомат", () => {
    expect(invalid(ceiling, "1500")).toBe(true);
    expect(invalid(ceiling, "2700")).toBe(false);
    expect(invalid(input, "16,5")).toBe(true);
    expect(invalid(input, "0")).toBe(true);
    expect(invalid(input, "40")).toBe(false);
    expect(invalid(input, "")).toBe(false);
  });
  it("другие вопросы: открытые, которых нет среди шагов", () => {
    const s = setup({ questions: [...setup().questions, q("q1", null), q("q2", null, "answered")] });
    expect(otherQuestions(s, wizardSteps(s, initialPicks(s)))).toBe(1);
  });
  it("вопросы за закрытой закладкой — не «другие», за открытой — шаги", () => {
    const s = setup();
    expect(otherQuestions(s, wizardSteps(s, { standby: "no", backup: "none" }))).toBe(0);
    expect(otherQuestions(s, wizardSteps(s, yes({})))).toBe(0);
  });
});
