// Запросы к серверу просмотра (service/viewer.py)

import type { Manifest, Page, Project, ProjectSummary } from "./types";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return (await r.json()) as T;
}

async function detail(r: Response): Promise<string> {
  try { return (await r.json()).detail; } catch { return r.statusText; }
}

export const enc = (path: string) => path.split("/").map(encodeURIComponent).join("/");
export const base = (name: string) => `/api/projects/${encodeURIComponent(name)}`;

export const listProjects = () => get<ProjectSummary[]>("/api/projects");
export const getProject = (name: string) => get<Project>(base(name));
export const getManifest = (name: string) => get<Manifest>(`${base(name)}/sheets`);
export const getPage = (name: string, index: number) => get<Page>(`${base(name)}/sheets/${index}`);

export async function getText(path: string): Promise<string> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return r.text();
}

export interface SaveAnswer { built: boolean; notes: string[] }

// Правки проводки → wiring.yaml и пересборка проекта
export async function saveWiring(name: string, body: unknown): Promise<SaveAnswer> {
  const r = await fetch(`${base(name)}/wiring`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}: ${await detail(r)}`);
  return (await r.json()) as SaveAnswer;
}
