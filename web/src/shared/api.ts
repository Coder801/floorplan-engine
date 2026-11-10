// Requests to the viewer server (service/viewer.py)

import i18n from "@/shared/i18n";
import type { Answer } from "./questions";
import type { Manifest, Page, PricePage, Project, ProjectSummary } from "./types";
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

// What the setup wizard writes: everything or nothing, with one rebuild
export interface WizardBody {
  variant?: { mode: string; route: string; distribution: string; path: string; conduit: string | null; plaster: string; rough_light: boolean; ceiling_height?: number };
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
