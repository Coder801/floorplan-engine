// Requests to the viewer server (service/viewer.py)

import i18n from "@/shared/i18n";
import type { Answer } from "./questions";
import type {
  Manifest, Page, PricePage, Project, ProjectSummary, WorkDomain, WorkOnBehalf, WorkPhotoRule, WorkState, WorkStatus,
} from "./types";
import { FORMAT_VERSION } from "./version";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return (await r.json()) as T;
}

async function detail(r: Response): Promise<string> {
  try { return (await r.json()).detail; } catch { return r.statusText; }
}

export const enc = (path: string) => path.split("/").map(encodeURIComponent).join("/");
export const base = (key: string) => `/api/projects/${encodeURIComponent(key)}`;
// The key from the address may be the id or an old link by name (invites, access codes): both open
export const isProject = (p: { id: string; name: string }, key: string | null) =>
  key !== null && (p.id === key || p.name === key);

export const listProjects = () => get<ProjectSummary[]>("/api/projects");
export const getProject = (name: string) => get<Project>(base(name));
// This page would draw sheets of another format version wrongly, so say so right away
export async function getManifest(name: string): Promise<Manifest> {
  const m = await get<Manifest>(`${base(name)}/sheets`);
  if (m.version !== FORMAT_VERSION) {
    throw new Error(i18n.t("api.format", { version: m.version, supported: FORMAT_VERSION }));
  }
  return m;
}
export const getPage = (name: string, index: number) => get<Page>(`${base(name)}/sheets/${index}`);

export async function getText(path: string): Promise<string> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return r.text();
}

export interface SaveAnswer { built: boolean; notes: string[] }

// Wiring edits → wiring.yaml and a project rebuild
export async function saveWiring(name: string, body: unknown): Promise<SaveAnswer> {
  const r = await fetch(`${base(name)}/wiring`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return (await r.json()) as SaveAnswer;
}

export interface AnswerResult { built: boolean; rebuilt: boolean }
export interface RefusedIssue { file: string; path: string; message: string }

// The check refused an answer (422): nothing changed. blockedBy: answered questions in its way
export class AnswerRefused extends Error {
  constructor(readonly issues: RefusedIssue[], readonly blockedBy: { id: string; text: string }[]) {
    super(issues.map((i) => i.message).join("; "));
  }
}

// One answer → answers.yaml and a rebuild (not for a text answer); null removes it
export async function saveAnswer(name: string, id: string, answer: Answer | null): Promise<AnswerResult> {
  const r = await fetch(`${base(name)}/answers`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, answer }),
  });
  return answerResult(r);
}

// The studio reviews a client answer: taken into account (a rebuild) or sent back with a comment
export type ReviewOutcome = "resolve" | "return";

export async function reviewAnswer(name: string, id: string, outcome: ReviewOutcome, comment?: string): Promise<AnswerResult> {
  const r = await fetch(`${base(name)}/answers/review`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, outcome, comment }),
  });
  return answerResult(r);
}

// What the setup wizard writes: everything or nothing, with one rebuild
export interface WizardBody {
  variant?: { mode: string; route: string; distribution: string; path: string; conduit: string | null; light_wiring: string; led_supply: string; plaster: string; rough_light: boolean; loop_conduit: string; ceiling_height?: number };
  answers?: Record<string, Answer | null>;
}

export async function saveWizard(name: string, body: WizardBody): Promise<AnswerResult> {
  const r = await fetch(`${base(name)}/wizard`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return answerResult(r);
}

async function answerResult(r: Response): Promise<AnswerResult> {
  if (r.status === 422) {
    const found = (await r.json()).detail as string | { issues: RefusedIssue[]; blocked_by: { id: string; text: string }[] };
    if (typeof found === "string") throw new Error(`422: ${found}`);
    throw new AnswerRefused(found.issues, found.blocked_by);
  }
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return (await r.json()) as AnswerResult;
}

// Studio price page: works, own price and the market (pipeline.price_page)
export const getPrices = () => get<PricePage>("/api/prices");

// Studio price edits → prices.yaml next to the projects; null removes the price
export async function savePrices(items: Record<string, number | null>): Promise<PricePage> {
  const r = await fetch("/api/prices", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }),
  });
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return (await r.json()) as PricePage;
}

// --- Installation by tasks (docs/service-api.md, "Просмотр: монтаж по задачам") ---------------
// Every write answers with the whole work state, as GET /work does: the page replaces its own.
// A broken rule is WorkError with the HTTP status and the server text (in Russian)

export class WorkError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function workCall(path: string, init?: RequestInit): Promise<WorkState> {
  const r = await fetch(path, init);
  if (!r.ok) throw new WorkError(r.status, await detail(r));
  return (await r.json()) as WorkState;
}
const json = (method: string, body?: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
});
const work = (key: string) => `${base(key)}/work`;
const id = encodeURIComponent;

export type WorkPlanAction = "propose" | "approve" | "close" | "discard";
export interface NewWorkLine { title: string; kind: "work" | "material"; unit?: string; qty: number; price?: number | null }
export interface NewWorkTask { title: string; description?: string; domain?: WorkDomain; photo?: WorkPhotoRule; lines?: NewWorkLine[] }
export interface WorkTaskEdit {
  title?: string; description?: string; position?: number; assignee_id?: string | null;
  materials_included?: boolean; photo?: WorkPhotoRule; after?: string[];
}

// The studio acting for the client sends how the client confirmed: {on_behalf, note?}; the client
// sends nothing (docs/service-api.md, "За заказчика")
export const behalfBody = (ob?: WorkOnBehalf | null) =>
  (ob ? { on_behalf: ob.channel, ...(ob.note.trim() ? { note: ob.note.trim() } : {}) } : {});

export const getWork = (key: string) => workCall(work(key));
export const createWorkPlan = (key: string) => workCall(`${work(key)}/plan`, json("POST"));
export const workPlanAction = (key: string, action: WorkPlanAction, onBehalf?: WorkOnBehalf | null) =>
  workCall(`${work(key)}/plan/${action}`, json("POST", onBehalf ? behalfBody(onBehalf) : undefined));
export const addWorkTask = (key: string, task: NewWorkTask) => workCall(`${work(key)}/tasks`, json("POST", task));
export const editWorkTask = (key: string, task: string, edit: WorkTaskEdit) => workCall(`${work(key)}/tasks/${id(task)}`, json("PATCH", edit));
export const deleteWorkTask = (key: string, task: string) => workCall(`${work(key)}/tasks/${id(task)}`, json("DELETE"));
export const setWorkStatus = (key: string, task: string, to: WorkStatus, comment?: string, onBehalf?: WorkOnBehalf | null) =>
  workCall(`${work(key)}/tasks/${id(task)}/status`, json("POST", { to, ...(comment ? { comment } : {}), ...behalfBody(onBehalf) }));
export const setWorkCheck = (key: string, task: string, index: number, checked: boolean) =>
  workCall(`${work(key)}/tasks/${id(task)}/checks`, json("PATCH", { index, checked }));
export const mergeWorkTask = (key: string, task: string, into: string) =>
  workCall(`${work(key)}/tasks/${id(task)}/merge`, json("POST", { into }));
export const moveWorkLines = (key: string, task: string, lineIds: string[], toTask: string) =>
  workCall(`${work(key)}/tasks/${id(task)}/lines/move`, json("POST", { line_ids: lineIds, to_task: toTask }));
export const editWorkLine = (key: string, task: string, line: string, edit: { fact_qty?: number | null; price?: number | null }) =>
  workCall(`${work(key)}/tasks/${id(task)}/lines/${id(line)}`, json("PATCH", edit));
export const addWorkLine = (key: string, task: string, line: NewWorkLine) => workCall(`${work(key)}/tasks/${id(task)}/lines`, json("POST", line));
export const addWorkComment = (key: string, task: string, text: string) => workCall(`${work(key)}/tasks/${id(task)}/comments`, json("POST", { text }));
export const addWorkPayment = (key: string, task: string, payment: { amount: number; paid_on: string; note?: string }) =>
  workCall(`${work(key)}/tasks/${id(task)}/payments`, json("POST", payment));
export const deleteWorkPayment = (key: string, payment: string) => workCall(`${work(key)}/payments/${id(payment)}`, json("DELETE"));
export const deleteWorkPhoto = (key: string, photo: string) => workCall(`${work(key)}/photos/${id(photo)}`, json("DELETE"));

// A photo or a PDF report: multipart, one file per request (the server takes one)
export function uploadWorkPhoto(key: string, task: string, file: File, caption = ""): Promise<WorkState> {
  const form = new FormData();
  form.append("file", file);
  if (caption) form.append("caption", caption);
  return workCall(`${work(key)}/tasks/${id(task)}/photos`, { method: "POST", body: form });
}
