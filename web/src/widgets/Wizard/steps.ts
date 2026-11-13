// Steps of the setup wizard: what is asked in this project, what is chosen, what goes to the
// server. Pure functions; the rules of the answers are model/intake.py and panel_questions.py.
// A step exists only while the project leaves the choice open: the variant steps by the summary
// and the right to choose, the panel steps by the panel questions of the report (a field fixed
// in electrical.yaml gives no question, so it is not asked).

import type { WizardBody } from "@/shared/api";
import { parseNumber, plainNumber, type Answer } from "@/shared/questions";
import type { OverviewMaster, OverviewReserve, Project, Question, VariantConduit, VariantDistribution, VariantLedSupply, VariantLightWiring, VariantLoopConduit, VariantPath, VariantPlaster, VariantRoute, Variants } from "@/shared/types";
import { parseCeiling } from "./ceiling";
import { activeSummary, availableRoutes, breakersOf, hasLoopDrops, modeConduit, modeOfBreakers, optionsOf, parseKey, type VariantChoice } from "@/widgets/VariantInfo/variants";

export type StepId = "route" | "distribution" | "lights" | "path" | "conduit" | "loopConduit" | "led" | "plaster" | "ceiling" | "rough" | "phases" | "input" | "breakers" | "standby" | "backup" | "power" | "inverter" | "battery" | "pv" | "npe" | "reserve" | "master" | "masterOff" | "labels" | "insulation" | "protection";
export type Picks = Partial<Record<StepId, string>>;
// "I don't know": the question closes with {accept}, the model keeps its typical value, and the
// person can come back to it later; the project is not held up by a device not chosen yet
export const UNKNOWN = "unknown";

export interface Step {
  id: StepId;
  group: "wiring" | "panel" | "reserve" | "extra";  // extra: work beyond the wiring, the estimate only
  kind: "cards" | "number" | "groups";  // cards with pictures, a field with presets, a list of panel groups
  options: string[];          // card values or field presets
  question?: Question;        // the report question behind the step; none yet if it needs another answer
  assumed?: string;           // what "don't know" leaves when no question stands behind the step
}

export interface Setup {
  questions: Question[];
  answers: Record<string, unknown>;
  variants: Variants | null;
  ceiling: number | null;
  reserve: OverviewReserve | null;  // none while the build has no backup bus: the "Panel" page asks later
  master: OverviewMaster | null;    // what the master switch can cut; none in an older build
  canChoose: boolean;
  canAnswer: boolean;
}

interface PanelStep { id: StepId; qid: string; kind: Step["kind"]; options: string[]; dc?: boolean; numeric?: boolean }

// In the order of the wizard; dc: only with an inverter (panel_questions._dc_questions)
const PANEL_STEPS: PanelStep[] = [
  { id: "phases", qid: "panel_phases", kind: "cards", options: ["1", "3"], numeric: true },
  { id: "input", qid: "panel_input", kind: "number", options: ["40", "50", "63", "80"], numeric: true },
  { id: "backup", qid: "panel_backup", kind: "cards", options: ["inverter", "plug", "station"] },
  { id: "power", qid: "panel_backup_power", kind: "number", options: ["3", "5", "6", "8", "10"], numeric: true },
  { id: "inverter", qid: "panel_inverter", kind: "cards", options: ["hybrid", "basic"], dc: true },
  { id: "battery", qid: "panel_battery", kind: "cards", options: ["12", "24", "48"], dc: true, numeric: true },
  { id: "pv", qid: "panel_pv", kind: "cards", options: ["0", "1", "2"], dc: true, numeric: true },
  { id: "npe", qid: "panel_npe", kind: "cards", options: ["yes", "no"], dc: true },
  { id: "reserve", qid: "panel_reserve", kind: "groups", options: [] },
  { id: "master", qid: "panel_master", kind: "cards", options: ["yes", "no"] },
  { id: "masterOff", qid: "panel_master_off", kind: "groups", options: [] },
];
// The master switch: in the "Panel" group, after the breakers (master.py)
const MASTER: ReadonlySet<StepId> = new Set(["master", "masterOff"]);
const CEILINGS = ["2500", "2700", "3000"];
const SUPPLY: ReadonlySet<StepId> = new Set(["phases", "input"]);  // the supply: the "Panel" group, first
// Options of the wiring variant; each changes the calculation (docs/wiring-variants.md)
export const VARIANT_STEPS: ReadonlySet<StepId> = new Set(["route", "distribution", "lights", "path", "conduit", "loopConduit", "led", "plaster", "rough", "breakers", "labels", "insulation", "protection"]);

export function setupOf(project: Project, variants: Variants | null, ceiling: number | null, reserve: OverviewReserve | null,
                        master: OverviewMaster | null = null): Setup {
  return {
    questions: project.report?.questions ?? [],
    answers: project.answers,
    variants,
    ceiling,
    reserve,
    master,
    canChoose: project.can?.choose_variant ?? true,
    canAnswer: project.can?.answer ?? false,  // an old server does not take answers
  };
}

const question = (setup: Setup, qid: string) => setup.questions.find((q) => q.id === qid);

// What an answered question holds as text; {accept} keeps the assumption
function answered(setup: Setup, q: Question | undefined): string | undefined {
  const a = q ? setup.answers[q.id] : undefined;
  if (Array.isArray(a)) return a.join();
  if (typeof a === "object" && a !== null && "accept" in a) return plainNumber(q?.assumption);
  return typeof a === "number" || typeof a === "string" ? plainNumber(a) : undefined;
}

// What the project holds now: the variant, the ceiling and the answers; an open question has no
// pick, and its assumption is only marked on its card
export function initialPicks(setup: Setup): Picks {
  const picks: Picks = {};
  if (setup.variants) {
    const { mode, route } = parseKey(setup.variants.active);
    const item = activeSummary(setup.variants);
    const { path, conduit, light_wiring, led_supply, plaster, rough_light, panel_labels, insulation_test, protection_test, loop_conduit } = optionsOf(item, mode);
    Object.assign(picks, {
      route, distribution: item?.distribution ?? "boxes", lights: light_wiring, path,
      // "don't know" is the conduit not chosen: the mode gives it; an older build has no choice to show
      conduit: setup.variants.conduit === null ? UNKNOWN : conduit, led: led_supply, plaster, rough: rough_light ? "yes" : "no", loopConduit: loop_conduit,
      breakers: breakersOf(mode),
      labels: panel_labels ? "yes" : "no", insulation: insulation_test ? "yes" : "no",
      protection: protection_test ? "yes" : "no",
    });
  }
  if (setup.ceiling !== null) picks.ceiling = plainNumber(setup.ceiling);
  for (const s of PANEL_STEPS) {
    const q = question(setup, s.qid);
    const a = q ? setup.answers[q.id] : undefined;
    const value = typeof a === "object" && a !== null && "accept" in a ? UNKNOWN : answered(setup, q);
    if (value !== undefined) picks[s.id] = value;
  }
  if (picks.backup !== undefined) picks.standby = picks.backup === "none" ? "no" : picks.backup === UNKNOWN ? LATER : "yes";
  return picks;
}

// "A provision for backup: provide and skip": the panel gets the backup the model assumes (the
// question closes with {accept}), and the backup steps are not asked; they can be answered later
export const LATER = "later";

// The choice "a provision for backup" decides the backup: "no" is the answer "none", "provide
// and skip" keeps the assumption of the model, and "calculate now" leaves the kind of backup to
// choose (a kind chosen before stays)
export function applyPick(picks: Picks, id: StepId, value: string): Picks {
  if (id !== "standby") return { ...picks, [id]: value };
  const { backup, ...rest } = picks;
  if (value === "no") return { ...rest, standby: "no", backup: "none" };
  if (value === LATER) return { ...rest, standby: LATER, backup: UNKNOWN };
  return { ...rest, standby: "yes", ...(backup === undefined || backup === "none" || backup === UNKNOWN ? {} : { backup }) };
}

// The wiring variant the choices lead to
export function variantOf(setup: Setup, picks: Picks): VariantChoice {
  return {
    mode: modeOfBreakers(picks.breakers) ?? parseKey(setup.variants!.active).mode,
    route: picks.route as VariantRoute,
    distribution: picks.distribution as VariantDistribution,
    path: picks.path as VariantPath,
    conduit: picks.conduit === UNKNOWN ? null : picks.conduit as VariantConduit,
    light_wiring: (picks.lights ?? "boxes") as VariantLightWiring,
    led_supply: (picks.led ?? "room") as VariantLedSupply,
    plaster: picks.plaster as VariantPlaster,
    rough_light: picks.rough === "yes",
    panel_labels: picks.labels !== "no",
    insulation_test: picks.insulation !== "no",
    protection_test: picks.protection === "yes",
    loop_conduit: (picks.loopConduit ?? "separate") as VariantLoopConduit,
  };
}

// Which chases stay with the cable before the plaster: conduit does not fit in the plaster layer
// (chases.before_plaster). "all": conduit in the walls; "floor": the floor lines, always in
// conduit. "Don't know" is never the walls: no mode puts conduit there
export function chasesKept(picks: Picks): "all" | "floor" | null {
  if (picks.plaster !== "before") return null;
  if (picks.conduit === "walls") return "all";
  return picks.route === "floor" ? "floor" : null;
}

// Backup in the model now: an answer or the assumption; null: no such question
function backupNow(setup: Setup): string | null {
  const q = question(setup, "panel_backup");
  return q ? answered(setup, q) ?? plainNumber(q.assumption) : null;
}

// The backup the choice leads to: "don't know" and a provision with no kind chosen yet keep the
// assumption of the model
function backupOf(setup: Setup, picks: Picks): string | null {
  const assumed = picks.backup === UNKNOWN || (picks.standby === "yes" && !isPicked(picks.backup));
  if (assumed) return plainNumber(question(setup, "panel_backup")?.assumption);
  return picks.backup ?? backupNow(setup);
}

// The master switch in the model now: an answer or the assumption; a choice fixed in YAML shows
// in the build (no question)
function masterNow(setup: Setup): string {
  const q = question(setup, "panel_master");
  if (q) return answered(setup, q) ?? plainNumber(q.assumption);
  return setup.master?.active ? "yes" : "no";
}

// The master switch the choice leads to: "don't know" keeps the assumption
function masterOf(setup: Setup, picks: Picks): string {
  if (picks.master === UNKNOWN) {
    const assumed = question(setup, "panel_master")?.assumption;
    return assumed == null ? "no" : plainNumber(assumed);
  }
  return isPicked(picks.master) ? picks.master! : masterNow(setup);
}

// What it cuts is asked with the master switch: the question appears with the answer "yes", the
// groups come from the build; with the switch already on, only while the report asks it
function masterShown(step: PanelStep, setup: Setup, picks: Picks): boolean {
  if (step.id === "master") return !!question(setup, step.qid);
  if (!setup.master || masterOf(setup, picks) !== "yes") return false;
  return !!question(setup, step.qid) || masterNow(setup) !== "yes";
}

// All of the backup waits for "a provision for backup: calculate now" ("provide and skip" asks
// none of it); a backup fixed in YAML has no such question. With a backup other than the inverter the report has no inverter questions: they
// appear with the answer. With the inverter in the model the report is exact: a missing one is
// fixed in YAML
function shown(step: PanelStep, setup: Setup, picks: Picks): boolean {
  if (MASTER.has(step.id)) return masterShown(step, setup, picks);
  const now = backupNow(setup);
  const open = now === null || picks.standby === "yes";
  if (step.id === "backup") return now !== null && open;
  if (step.kind === "groups") return open && !!setup.reserve && !!question(setup, step.qid) && backupOf(setup, picks) !== "none";
  // The power of any backup: asked with it; with no backup in the model yet, it appears with the answer
  if (step.id === "power") {
    if (now === null) return !!question(setup, step.qid);
    const backup = backupOf(setup, picks);
    return open && !!backup && backup !== "none" && (now === "none" || !!question(setup, step.qid));
  }
  if (!step.dc || now === null) return !!question(setup, step.qid);
  if (!open || backupOf(setup, picks) !== "inverter") return false;
  return now !== "inverter" || !!question(setup, step.qid);
}

export function wizardSteps(setup: Setup, picks: Picks): Step[] {
  const steps: Step[] = [];
  const choosing = setup.canChoose && !!setup.variants;
  if (choosing) {
    const routes = availableRoutes(setup.variants!);
    if (routes.length > 1) steps.push({ id: "route", group: "wiring", kind: "cards", options: routes });
    steps.push({ id: "distribution", group: "wiring", kind: "cards", options: ["boxes", "loop"] });
    steps.push({ id: "lights", group: "wiring", kind: "cards", options: ["boxes", "chain"] });
    steps.push({ id: "path", group: "wiring", kind: "cards", options: ["right", "shortest"] });
    const mode = modeOfBreakers(picks.breakers) ?? parseKey(setup.variants!.active).mode;
    steps.push({ id: "conduit", group: "wiring", kind: "cards", options: ["none", "ceiling", "walls", UNKNOWN], assumed: modeConduit(mode) });
    // Only while chain drops go in conduit: a daisy chain with conduit in the walls or on the floor
    const conduit = picks.conduit === UNKNOWN ? null : picks.conduit as VariantConduit | undefined;
    if (hasLoopDrops({ distribution: picks.distribution as VariantDistribution, route: picks.route as VariantRoute, conduit: conduit ?? null, mode })) {
      steps.push({ id: "loopConduit", group: "wiring", kind: "cards", options: ["separate", "shared"] });
    }
    // Only with LED outputs in the project (pipeline.variant_block led)
    if (setup.variants!.led) steps.push({ id: "led", group: "wiring", kind: "cards", options: ["room", "board"] });
    steps.push({ id: "plaster", group: "wiring", kind: "cards", options: ["after", "before"] });
    if (setup.ceiling !== null) steps.push({ id: "ceiling", group: "wiring", kind: "number", options: CEILINGS });
    steps.push({ id: "rough", group: "wiring", kind: "cards", options: ["no", "yes"] });
  }
  const panel: Step[] = !setup.canAnswer ? [] : PANEL_STEPS.filter((s) => shown(s, setup, picks)).map((s) => {
    const list = s.id === "masterOff" ? setup.master : setup.reserve;
    const options = s.kind === "groups" ? list?.items.map((g) => g.id) ?? []
      : s.kind === "cards" ? [...s.options, UNKNOWN] : s.options;
    const group = SUPPLY.has(s.id) || MASTER.has(s.id) ? "panel" : "reserve";
    return { id: s.id, group, kind: s.kind, options, question: question(setup, s.qid) };
  });
  const input = panel.filter((s) => SUPPLY.has(s.id));
  const master = panel.filter((s) => MASTER.has(s.id));
  const rest = panel.filter((s) => !SUPPLY.has(s.id) && !MASTER.has(s.id));
  steps.push(...input);
  if (choosing) steps.push({ id: "breakers", group: "panel", kind: "cards", options: ["simple", "groups", "lines"] });
  steps.push(...master);
  if (setup.canAnswer && question(setup, "panel_backup")) {
    steps.push({ id: "standby", group: "reserve", kind: "cards", options: ["no", LATER, "yes"], question: question(setup, "panel_backup") });
  }
  steps.push(...rest);
  // Extra options: work beyond the wiring itself, they change only the estimate
  if (choosing) {
    steps.push({ id: "labels", group: "extra", kind: "cards", options: ["yes", "no"] });
    steps.push({ id: "insulation", group: "extra", kind: "cards", options: ["yes", "no"] });
    steps.push({ id: "protection", group: "extra", kind: "cards", options: ["yes", "no"] });
  }
  return steps;
}

// A typed number that cannot be saved: the ceiling out of its limits, a breaker not in whole
// amperes; the backup power is kW with a fraction (3.6)
export function invalid(step: Step, pick: string | undefined): boolean {
  if (step.kind !== "number" || pick === undefined || pick === "" || pick === UNKNOWN) return false;
  if (step.id === "ceiling") return parseCeiling(pick) === null;
  const n = parseNumber(pick);
  return n === null || n <= 0 || (step.id !== "power" && !Number.isInteger(n));
}

// The i18n key of a card name; the route step names its cards as the variant does
export const optionKey = (step: StepId, value: string): string =>
  (step === "route" ? `variant.routes.${value}` : `wizard.steps.${step}.options.${value}.name`);

export const isPicked = (pick: string | undefined) => pick !== undefined && pick !== "";

// Steps that may stay without an answer: they only move groups inside the panel the model has
// already put together. Every other step changes the price (cable, work, panel devices), so it
// is required: with one of them unanswered nothing is recalculated. "Don't know" is an answer
const OPTIONAL: ReadonlySet<StepId> = new Set(["reserve", "masterOff"]);
export const isRequired = (id: StepId) => !OPTIONAL.has(id);

// Required steps of the wizard still without an answer
export function missingSteps(steps: Step[], picks: Picks): Step[] {
  return steps.filter((s) => isRequired(s.id) && !isPicked(picks[s.id]));
}

function asAnswer(s: PanelStep, pick: string): Answer {
  if (pick === UNKNOWN) return { accept: true };
  if (s.kind === "groups") return pick.split(",");
  return s.numeric ? parseNumber(pick) ?? pick : pick;
}

// An answer that the model refuses without its backup: the inverter ones, and the bus with none
function goesWithBackup(s: PanelStep, setup: Setup, picks: Picks): boolean {
  const backup = backupOf(setup, picks);
  return backupNow(setup) !== null && (s.dc ? backup !== "inverter" : (s.kind === "groups" || s.id === "power") && backup === "none");
}

// What changes: the variant if any of its parts differs, the answers that differ. Answers of a
// backup that is gone go away with it: the model refuses them together. "A provision: no" is the
// answer "none" with its step hidden, "provide and skip" is "keep the assumption" the same way;
// "calculate now" with no kind chosen takes that answer back
export function wizardBody(setup: Setup, picks: Picks): WizardBody {
  const before = initialPicks(setup);
  const body: WizardBody = {};
  const visible = wizardSteps(setup, picks);
  const step = (id: StepId) => visible.find((s) => s.id === id);
  if (setup.canChoose && setup.variants) {
    const ceiling = step("ceiling") && picks.ceiling && picks.ceiling !== before.ceiling ? parseCeiling(picks.ceiling) : null;
    if ([...VARIANT_STEPS].some((id) => picks[id] !== before[id]) || ceiling !== null) {
      body.variant = { ...variantOf(setup, picks), ...(ceiling !== null ? { ceiling_height: ceiling } : {}) };
    }
  }
  const answers: Record<string, Answer | null> = {};
  for (const s of PANEL_STEPS) {
    const pick = picks[s.id];
    const asked = step(s.id) || (s.id === "backup" && (picks.standby === "no" || picks.standby === LATER));
    if (asked && isPicked(pick) && pick !== before[s.id]) answers[s.qid] = asAnswer(s, pick!);
    if (s.id === "backup" && picks.standby === "yes" && !isPicked(pick) && setup.answers[s.qid] !== undefined) answers[s.qid] = null;
    if (setup.canAnswer && goesWithBackup(s, setup, picks) && setup.answers[s.qid] !== undefined) answers[s.qid] = null;
    // What the master switch cuts goes away with it: the model refuses it without the switch
    if (s.id === "masterOff" && masterOf(setup, picks) === "no" && setup.answers[s.qid] !== undefined) answers[s.qid] = null;
  }
  if (Object.keys(answers).length) body.answers = answers;
  return body;
}

// How far the setup is: steps of the project and those still without a decision. A step of the
// variant always holds a value, and an unchanged one writes nothing, so only questions stay open
export interface SetupProgress { total: number; open: StepId[]; steps: StepId[] }

export function setupProgress(setup: Setup): SetupProgress {
  const picks = initialPicks(setup);
  const steps = wizardSteps(setup, picks);
  return {
    total: steps.length,
    open: steps.filter((s) => !isPicked(picks[s.id])).map((s) => s.id),
    steps: steps.map((s) => s.id),
  };
}

// Open questions the wizard does not ask: they stay in the "Questions" panel. Those behind a
// closed "provision for backup" are not counted: its answer decides if they exist at all, and
// "provide and skip" puts them off on purpose
export function otherQuestions(setup: Setup, steps: Step[]): number {
  const asked = new Set(steps.flatMap((s) => (s.question ? [s.question.id] : [])));
  const closed = steps.some((s) => s.id === "standby") && !steps.some((s) => s.id === "backup");
  if (closed) PANEL_STEPS.filter((s) => s.dc || s.id === "reserve" || s.id === "power").forEach((s) => asked.add(s.qid));
  return setup.questions.filter((q) => (q.state === "open" || q.state === "text") && !asked.has(q.id)).length;
}
