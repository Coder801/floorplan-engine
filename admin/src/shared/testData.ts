// Synthetic answers of the admin API for component tests: each factory gives a full record,
// a test overrides only the fields it is about.
import type {
  EventRow, FeedbackItem, FeedbackPage, InviteRow, ProjectDetail, ProjectRow, StudioDetail, StudioRow, UserBrief, UserDetail, UserRow,
} from "./types";

export const person = (over: Partial<UserBrief> = {}): UserBrief => ({
  id: "u1", name: "Иван Петров", email: "ivan@example.com", phone: null, account_type: "pro",
  superuser: false, active: true, last_login: null, created: "2026-11-01T10:00:00Z", ...over,
});

export const userRow = (over: Partial<UserRow> = {}): UserRow => ({ ...person(), space: null, ...over });

export const userDetail = (over: Partial<UserDetail> = {}): UserDetail => ({
  ...person(), space: null, projects: [], providers: ["email"], sessions: [], ...over,
});

const studioBase = { business: null, city: "", phone: "", folder: "studio", created: "2026-10-01T10:00:00Z" };

export const studioRow = (over: Partial<StudioRow> = {}): StudioRow => ({
  id: "s1", name: "Ампер", kind: "studio", ...studioBase, members: 2, projects: 1, ...over,
});

export const studioDetail = (over: Partial<StudioDetail> = {}): StudioDetail => ({
  id: "s1", name: "Ампер", kind: "studio", ...studioBase, members: [], projects: [], invites: [], ...over,
});

export const projectRow = (over: Partial<ProjectRow> = {}): ProjectRow => ({
  id: "p1", name: "Квартира на Нагорной", slug: "nahirna-16", studio: { id: "s1", name: "Ампер" },
  state: "active", created: "2026-10-05T10:00:00Z", services: ["electrical", "plumbing"], members: 1, ...over,
});

export const projectDetail = (over: Partial<ProjectDetail> = {}): ProjectDetail => ({
  id: "p1", name: "Квартира на Нагорной", slug: "nahirna-16", studio: { id: "s1", name: "Ампер" },
  state: "active", created: "2026-10-05T10:00:00Z", services: ["electrical", "plumbing"], members: [], codes: [], invites: [], support: [], ...over,
});

export const invite = (over: Partial<InviteRow> = {}): InviteRow => ({
  id: "i1", role: "client", email: "owner@example.com", state: "active", created: null, expires: null, accepted_by: null, ...over,
});

export const event = (over: Partial<EventRow> = {}): EventRow => ({
  id: "e1", action: "login", at: "2026-11-10T10:00:00Z", user: person(), subject: null, studio: null, project: null,
  payload: {}, ...over,
});

export const feedbackItem = (over: Partial<FeedbackItem> = {}): FeedbackItem => ({
  id: "f1", created_at: "2026-11-12T10:00:00Z", kind: "bug", text: "Не открывается лист", status: "new",
  admin_note: null, context: null, author: { name: "Иван", email: "ivan@example.com" }, project: null, photos: [], ...over,
});

export const feedbackPage = (items: FeedbackItem[], over: Partial<FeedbackPage> = {}): FeedbackPage => ({
  items, total: items.length, counts: { new: items.length, seen: 0, done: 0 }, ...over,
});
