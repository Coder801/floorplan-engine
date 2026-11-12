// Requests to the admin API /api/admin/* (service/api/admin.py). A broken access rule comes back
// as 409 with a Russian reason: it is thrown as ApiError and shown next to the action.
import type {
  EventRow, FeedbackItem, FeedbackPage, FeedbackStatus, Me, ProjectDetail, ProjectRow, StudioDetail, StudioRow, Summary, UserDetail, UserRow,
} from "./types";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const d = (await r.json()).detail;
      detail = typeof d === "string" ? d : JSON.stringify(d);
    } catch { /* not JSON */ }
    throw new ApiError(r.status, detail);
  }
  return (await r.json()) as T;
}

const A = "/api/admin";
const q = encodeURIComponent;

export const me = () => call<Me>("GET", "/api/auth/me");
export const summary = () => call<Summary>("GET", `${A}/summary`);

export const studios = () => call<StudioRow[]>("GET", `${A}/studios`);
export const studio = (id: string) => call<StudioDetail>("GET", `${A}/studios/${q(id)}`);
export const addStudioMember = (id: string, user: string, role: string) =>
  call<StudioDetail>("POST", `${A}/studios/${q(id)}/members`, { user, role });
export const setStudioRole = (id: string, user: string, role: string) =>
  call<StudioDetail>("PATCH", `${A}/studios/${q(id)}/members/${q(user)}`, { role });
export const removeStudioMember = (id: string, user: string) =>
  call<StudioDetail>("DELETE", `${A}/studios/${q(id)}/members/${q(user)}`);
export const studioInvite = (id: string, role: string, email: string | null, days: number) =>
  call<{ url: string }>("POST", `${A}/studios/${q(id)}/invites`, { role, email, days });

export const users = (search = "") => call<UserRow[]>("GET", `${A}/users?q=${q(search)}`);
export const user = (id: string) => call<UserDetail>("GET", `${A}/users/${q(id)}`);
export const setActive = (id: string, active: boolean) =>
  call<UserDetail>("POST", `${A}/users/${q(id)}/active`, { active });
export const logout = (id: string) => call<UserDetail>("POST", `${A}/users/${q(id)}/logout`);

export const projects = () => call<ProjectRow[]>("GET", `${A}/projects`);
export const project = (id: string) => call<ProjectDetail>("GET", `${A}/projects/${q(id)}`);
export const addProjectMember = (id: string, user: string, role: string) =>
  call<ProjectDetail>("POST", `${A}/projects/${q(id)}/members`, { user, role });
export const removeProjectMember = (id: string, user: string) =>
  call<ProjectDetail>("DELETE", `${A}/projects/${q(id)}/members/${q(user)}`);
export const projectInvite = (id: string, role: string, email: string | null, days: number) =>
  call<{ url: string }>("POST", `${A}/projects/${q(id)}/invites`, { role, email, days });
export const revokeInvite = (invite: string) => call<{ ok: boolean }>("DELETE", `${A}/invites/${q(invite)}`);
export const issueCode = (id: string, role: string, label: string, days: number) =>
  call<{ code: string }>("POST", `${A}/projects/${q(id)}/codes`, { role, label, days });
export const revokeCode = (id: string, code: string) =>
  call<ProjectDetail>("DELETE", `${A}/projects/${q(id)}/codes/${q(code)}`);
export const grantSupport = (id: string, user: string, reason: string, hours: number) =>
  call<ProjectDetail>("POST", `${A}/projects/${q(id)}/support`, { user, reason, hours });
export const revokeSupport = (id: string, user: string) =>
  call<ProjectDetail>("DELETE", `${A}/projects/${q(id)}/support/${q(user)}`);

export const events = (filter: { project?: string; user?: string; limit?: number } = {}) => {
  const p = new URLSearchParams();
  if (filter.project) p.set("project", filter.project);
  if (filter.user) p.set("user", filter.user);
  p.set("limit", String(filter.limit ?? 200));
  return call<EventRow[]>("GET", `${A}/events?${p}`);
};

// Product feedback: a filter by status and kind, a search over the text and the author, a page
export interface FeedbackFilter { status?: string; kind?: string; q?: string; offset?: number; limit?: number }
export const feedback = (filter: FeedbackFilter = {}) => {
  const p = new URLSearchParams();
  for (const k of ["status", "kind", "q"] as const) if (filter[k]) p.set(k, filter[k]);
  p.set("offset", String(filter.offset ?? 0));
  p.set("limit", String(filter.limit ?? 50));
  return call<FeedbackPage>("GET", `${A}/feedback?${p}`);
};
export const updateFeedback = (id: string, change: { status?: FeedbackStatus; admin_note?: string }) =>
  call<FeedbackItem>("PATCH", `${A}/feedback/${q(id)}`, change);
