// Steps of the setup wizard: what is asked in this project, what is chosen, what goes to the
// server. Pure functions; the rules of the answers are model/intake.py and panel_questions.py.
// A step exists only while the project leaves the choice open: the variant steps by the summary
// and the right to choose, the panel steps by the panel questions of the report (a field fixed
// in electrical.yaml gives no question, so it is not asked).

import type { WizardBody } from "@/shared/api";
import { parseNumber, plainNumber, type Answer } from "@/shared/questions";
import type { OverviewReserve, Project, Question, VariantDistribution, VariantPath, VariantPlaster, VariantRoute, Variants } from "@/shared/types";
import { parseCeiling } from "./ceiling";
import { activeSummary, availableRoutes, breakersOf, modeOfBreakers, optionsOf, parseKey, type VariantChoice } from "@/widgets/VariantInfo/variants";

export type StepId = "route" | "distribution" | "path" | "conduit" | "plaster" | "ceiling" | "rough" | "input" | "breakers" | "standby" | "backup" | "inverter" | "battery" | "pv" | "npe" | "reserve";
export type Picks = Partial<Record<StepId, string>>;
// "I don't know": the question closes with {accept}, the model keeps its typical value, and the
// person can come back to it later; the project is not held up by a device not chosen yet
export const UNKNOWN = "unknown";

export interface Step {
  id: StepId;
  group: "wiring" | "panel" | "reserve";
  kind: "cards" | "number" | "groups";  // cards with pictures, a field with presets, a list of panel groups
  options: string[];          // card values or field presets
  question?: Question;        // the report question behind the step; none yet if it needs another answer
}

export interface Setup {
  questions: Question[];
  answers: Record<string, unknown>;
  variants: Variants | null;
  ceiling: number | null;
  reserve: OverviewReserve | null;  // none while the build has no backup bus: the "Panel" page asks later
  canChoose: boolean;
  canAnswer: boolean;
}

interface PanelStep { id: StepId; qid: string; kind: Step["kind"]; options: string[]; dc?: boolean; numeric?: boolean }

// In the order of the wizard; dc: only with an inverter (panel_questions._dc_questions)
const PANEL_STEPS: PanelStep[] = [
  { id: "input", qid: "panel_input", kind: "number", options: ["25", "32", "40", "50", "63"], numeric: true },
  { id: "backup", qid: "panel_backup", kind: "cards", options: ["inverter", "plug", "station"] },
  { id: "inverter", qid: "panel_inverter", kind: "cards", options: ["hybrid", "basic"], dc: true },
  { id: "battery", qid: "panel_battery", kind: "cards", options: ["12", "24", "48"], dc: true, numeric: true },
  { id: "pv", qid: "panel_pv", kind: "cards", options: ["0", "1", "2"], dc: true, numeric: true },
  { id: "npe", qid: "panel_npe", kind: "cards", options: ["yes", "no"], dc: true },
  { id: "reserve", qid: "panel_reserve", kind: "groups", options: [] },
];
const CEILINGS = ["2500", "2700", "3000"];
// Options of the wiring variant; each changes the calculation (docs/wiring-variants.md)
export const VARIANT_STEPS: ReadonlySet<StepId> = new Set(["route", "distribution", "path", "conduit", "plaster", "rough", "breakers"]);

export function setupOf(project: Project, variants: Variants | null, ceiling: number | null, reserve: OverviewReserve | null): Setup {
  return {
    questions: project.report?.questions ?? [],
    answers: project.answers,
    variants,
    ceiling,
    reserve,
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
    const { path, conduit, plaster, rough_light } = optionsOf(item, mode);
    Object.assign(picks, {
      route, distribution: item?.distribution ?? "boxes", path,
      conduit: conduit ? "tube" : "plain", plaster, rough: rough_light ? "yes" : "no",
      breakers: breakersOf(mode),
    });
  }
  if (setup.ceiling !== null) picks.ceiling = plainNumber(setup.ceiling);
  for (const s of PANEL_STEPS) {
    const q = question(setup, s.qid);
    const a = q ? setup.answers[q.id] : undefined;
    const value = typeof a === "object" && a !== null && "accept" in a ? UNKNOWN : answered(setup, q);
    if (value !== undefined) picks[s.id] = value;
  }
  if (picks.backup !== undefined) picks.standby = picks.backup === "none" ? "no" : "yes";
  return picks;
}

// The choice "a provision for backup" decides the backup: "no" is the answer "none", and "yes"
// after it leaves the kind of backup to choose
export function applyPick(picks: Picks, id: StepId, value: string): Picks {
  if (id !== "standby") return { ...picks, [id]: value };
  const { backup, ...rest } = picks;
  if (value === "no") return { ...rest, standby: "no", backup: "none" };
  return { ...rest, standby: "yes", ...(backup === undefined || backup === "none" ? {} : { backup }) };
}

// The wiring variant the choices lead to
export function variantOf(setup: Setup, picks: Picks): VariantChoice {
  return {
    mode: modeOfBreakers(picks.breakers) ?? parseKey(setup.variants!.active).mode,
    route: picks.route as VariantRoute,
    distribution: picks.distribution as VariantDistribution,
    path: picks.path as VariantPath,
    conduit: picks.conduit === "tube",
    plaster: picks.plaster as VariantPlaster,
    rough_light: picks.rough === "yes",
  };
}

// Which chases stay with the cable before the plaster: conduit does not fit in the plaster layer
// (chases.before_plaster). "all": ceiling conduit; "floor": the floor lines, always in conduit
export function chasesKept(picks: Picks): "all" | "floor" | null {
  if (picks.plaster !== "before") return null;
  if (picks.conduit === "tube") return "all";
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

// All of the backup waits for "a provision for backup: yes"; a backup fixed in YAML has no such
// question. With a backup other than the inverter the report has no inverter questions: they
// appear with the answer. With the inverter in the model the report is exact: a missing one is
// fixed in YAML
function shown(step: PanelStep, setup: Setup, picks: Picks): boolean {
  const now = backupNow(setup);
  const open = now === null || picks.standby === "yes";
  if (step.id === "backup") return now !== null && open;
  if (step.kind === "groups") return open && !!setup.reserve && !!question(setup, step.qid) && backupOf(setup, picks) !== "none";
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
    steps.push({ id: "path", group: "wiring", kind: "cards", options: ["right", "shortest"] });
    steps.push({ id: "conduit", group: "wiring", kind: "cards", options: ["plain", "tube"] });
    steps.push({ id: "plaster", group: "wiring", kind: "cards", options: ["after", "before"] });
    if (setup.ceiling !== null) steps.push({ id: "ceiling", group: "wiring", kind: "number", options: CEILINGS });
    steps.push({ id: "rough", group: "wiring", kind: "cards", options: ["no", "yes"] });
  }
  const panel: Step[] = !setup.canAnswer ? [] : PANEL_STEPS.filter((s) => shown(s, setup, picks)).map((s) => {
    const options = s.kind === "groups" ? setup.reserve?.items.map((g) => g.id) ?? []
      : s.kind === "cards" ? [...s.options, UNKNOWN] : s.options;
    return { id: s.id, group: s.id === "input" ? "panel" : "reserve", kind: s.kind, options, question: question(setup, s.qid) };
  });
  const [input, rest] = [panel.filter((s) => s.id === "input"), panel.filter((s) => s.id !== "input")];
  steps.push(...input);
  if (choosing) steps.push({ id: "breakers", group: "panel", kind: "cards", options: ["simple", "groups", "lines"] });
  if (setup.canAnswer && question(setup, "panel_backup")) {
    steps.push({ id: "standby", group: "reserve", kind: "cards", options: ["no", "yes"], question: question(setup, "panel_backup") });
  }
  steps.push(...rest);
  return steps;
}

// A typed number that cannot be saved: the ceiling out of its limits, a breaker not in whole amperes
export function invalid(step: Step, pick: string | undefined): boolean {
  if (step.kind !== "number" || pick === undefined || pick === "" || pick === UNKNOWN) return false;
  if (step.id === "ceiling") return parseCeiling(pick) === null;
  const n = parseNumber(pick);
  return n === null || n <= 0 || !Number.isInteger(n);
}

export const isPicked = (pick: string | undefined) => pick !== undefined && pick !== "";

function asAnswer(s: PanelStep, pick: string): Answer {
  if (pick === UNKNOWN) return { accept: true };
  if (s.kind === "groups") return pick.split(",");
  return s.numeric ? parseNumber(pick) ?? pick : pick;
}

// An answer that the model refuses without its backup: the inverter ones, and the bus with none
function goesWithBackup(s: PanelStep, setup: Setup, picks: Picks): boolean {
  const backup = backupOf(setup, picks);
  return backupNow(setup) !== null && (s.dc ? backup !== "inverter" : s.kind === "groups" && backup === "none");
}

// What changes: the variant if any of its parts differs, the answers that differ. Answers of a
// backup that is gone go away with it: the model refuses them together. "A provision: no" is the
// answer "none" with its step hidden; "yes" with no kind chosen takes that answer back
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
    const asked = step(s.id) || (s.id === "backup" && picks.standby === "no");
    if (asked && isPicked(pick) && pick !== before[s.id]) answers[s.qid] = asAnswer(s, pick!);
    if (s.id === "backup" && picks.standby === "yes" && !isPicked(pick) && setup.answers[s.qid] !== undefined) answers[s.qid] = null;
    if (setup.canAnswer && goesWithBackup(s, setup, picks) && setup.answers[s.qid] !== undefined) answers[s.qid] = null;
  }
  if (Object.keys(answers).length) body.answers = answers;
  return body;
}

// How far the setup is: steps of the project and those still without a decision. A step of the
// variant always holds a value, and an unchanged one writes nothing, so only questions stay open
export function setupProgress(setup: Setup): { total: number; open: StepId[] } {
  const picks = initialPicks(setup);
  const steps = wizardSteps(setup, picks);
  return { total: steps.length, open: steps.filter((s) => !isPicked(picks[s.id])).map((s) => s.id) };
}

// Open questions the wizard does not ask: they stay in the "Questions" panel. Those behind a
// closed "provision for backup" are not counted: its answer decides if they exist at all
export function otherQuestions(setup: Setup, steps: Step[]): number {
  const asked = new Set(steps.flatMap((s) => (s.question ? [s.question.id] : [])));
  const closed = steps.some((s) => s.id === "standby") && !steps.some((s) => s.id === "backup");
  if (closed) PANEL_STEPS.filter((s) => s.dc || s.kind === "groups").forEach((s) => asked.add(s.qid));
  return setup.questions.filter((q) => (q.state === "open" || q.state === "text") && !asked.has(q.id)).length;
}
