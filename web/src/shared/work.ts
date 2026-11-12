// Installation by tasks (docs/work-tasks.md): what the "Tasks" tab shows and which buttons it
// offers, from the work state of the API (GET /work). The server checks every rule again; here
// only what to show. Rights come from state.can, never from role names.

import i18n from "./i18n";
import type {
  WorkCan, WorkChannel, WorkComment, WorkDomain, WorkOnBehalf, WorkPhoto, WorkPlan, WorkState, WorkStatus, WorkTask, WorkTotals,
} from "./types";

// Board columns in work order
export const STATUSES: readonly WorkStatus[] = ["proposed", "todo", "in_progress", "review", "returned", "accepted"];

// Who sees what: the studio and installers — the board; the client (accepts, does not work) and a
// view code — the list in work order
export type WorkLayout = "board" | "list";
export const layoutOf = (can: WorkCan): WorkLayout => (can.work_manage || can.work_do ? "board" : "list");

// Domain switch of the board: "all" also shows the studio's own tasks (domain other)
export type DomainFilter = "all" | Exclude<WorkDomain, "other">;
export const DOMAIN_FILTERS: readonly DomainFilter[] = ["all", "electrical", "plumbing"];
export const byDomain = (tasks: WorkTask[], f: DomainFilter) => (f === "all" ? tasks : tasks.filter((t) => t.domain === f));
// Domains present in the plan: the switch is shown only when there are two
export const domainsOf = (tasks: WorkTask[]) => [...new Set(tasks.map((t) => t.domain))];

export const ordered = (tasks: WorkTask[]) => [...tasks].sort((a, b) => a.position - b.position);

// Columns of the board: a plan not approved yet is one column of proposed tasks in work order;
// an approved one — the work columns, "proposed" only while there is an extra task to agree
export function boardColumns(plan: WorkPlan | null, tasks: WorkTask[]): WorkStatus[] {
  if (!plan) return [];
  if (plan.state === "draft" || plan.state === "proposed") return ["proposed"];
  return STATUSES.filter((s) => s !== "proposed" || tasks.some((t) => t.status === "proposed"));
}

export function byColumn(tasks: WorkTask[]): Record<WorkStatus, WorkTask[]> {
  const out = Object.fromEntries(STATUSES.map((s) => [s, [] as WorkTask[]])) as Record<WorkStatus, WorkTask[]>;
  for (const t of ordered(tasks)) out[t.status].push(t);
  return out;
}

// Everything accepted and paid: the studio may close the plan
export const allDone = (t: WorkTotals) => t.tasks > 0 && t.accepted === t.tasks && t.settled === t.tasks;

// Plan buttons by its state and the rights (POST /work/plan, /work/plan/{action}, /work/tasks)
export type PlanAction = "create" | "propose" | "discard" | "approve" | "add" | "close";
export function planActions(state: WorkState): PlanAction[] {
  const { plan, can } = state;
  if (!plan) return can.work_manage && state.draft_available ? ["create"] : [];
  const out: PlanAction[] = [];
  if (plan.state === "draft" && can.work_manage) out.push("propose", "discard");
  if (plan.state === "proposed") {
    if (can.work_accept) out.push("approve");
    if (can.work_manage) out.push("discard");
  }
  if (plan.state === "approved" && can.work_manage) {
    out.push("add");
    if (allDone(plan.totals)) out.push("close");
  }
  return out;
}

// The empty screen: what to say when there is nothing to show yet. The client does not see a
// draft the studio has not sent: for them it is the same "the studio is preparing the plan"
export type WorkEmpty = "create" | "noDraft" | "preparing" | null;
export function emptyOf(state: WorkState): WorkEmpty {
  const { plan, can } = state;
  if (plan && !(plan.state === "draft" && layoutOf(can) === "list")) return null;
  if (!can.work_manage) return "preparing";
  return state.draft_available ? "create" : "noDraft";
}

// --- The studio for the client (decision 2026-11-12) --------------------------------------------
// The client's actions (approve the plan, agree to extra work, accept, return) are work_accept.
// Whoever has it and is not the client side — the studio (owner, designer, superuser) — does them
// only for the client and says how the client confirmed; without the channel the server answers
// 422. The client side (client, client_code) accepts and nothing else, so it has work_accept
// without work_do and work_manage. The /work answer has no other sign of the role (docs/work-tasks.md)
export const CHANNELS: readonly WorkChannel[] = ["phone", "telegram", "other"];
export const NOTE_MAX = 500;
export const actsForClient = (can: WorkCan) => can.work_accept && (can.work_manage || can.work_do);

// The actions that are the client's: the studio asks "how did the client confirm?" before them
export type ClientAction = "approve" | "agree" | "accept" | "return";
const CLIENT_ACTIONS = new Set<string>(["approve", "agree", "accept", "return"]);
export const needsBehalf = (action: StatusAction | PlanAction, can: WorkCan) => CLIENT_ACTIONS.has(action) && actsForClient(can);

// The channel in words for the feed («студия за заказчика — по звонку: звонок 12.11») and the plan
// («Утверждён студией за заказчика — в Telegram»)
export function behalfText(ob: WorkOnBehalf, where: "feed" | "plan"): string {
  const head = i18n.t(`work.behalf.${where}`, { how: i18n.t(`work.behalf.how.${ob.channel}`) });
  return ob.note.trim() ? `${head}: ${ob.note.trim()}` : head;
}

// Status change → the right it needs (docs/service-api.md, transitions); in transition order
const TRANSITIONS: { from: WorkStatus; to: WorkStatus; right: keyof WorkCan; action: StatusAction }[] = [
  { from: "proposed", to: "todo", right: "work_accept", action: "agree" },
  { from: "todo", to: "in_progress", right: "work_do", action: "take" },
  { from: "in_progress", to: "review", right: "work_do", action: "handIn" },
  { from: "review", to: "accepted", right: "work_accept", action: "accept" },
  { from: "review", to: "returned", right: "work_accept", action: "return" },
  { from: "returned", to: "review", right: "work_do", action: "handIn" },
  { from: "returned", to: "in_progress", right: "work_do", action: "retake" },
];
export type StatusAction = "agree" | "take" | "handIn" | "accept" | "return" | "retake";

// A status button: blocked — shown disabled with a hint (photo: the task needs a photo first;
// waiting: other tasks are not accepted yet, only the studio may start it); comment — only with one
export interface StatusButton {
  to: WorkStatus;
  action: StatusAction;
  primary: boolean;
  comment: boolean;
  behalf: boolean;    // the studio does it for the client: ask the client's channel first
  blocked: "photo" | "waiting" | null;
}

export function statusButtons(task: WorkTask, plan: WorkPlan | null, can: WorkCan): StatusButton[] {
  if (plan?.state !== "approved") return [];
  return TRANSITIONS.filter((tr) => tr.from === task.status && can[tr.right]).map((tr, i) => ({
    to: tr.to,
    action: tr.action,
    primary: i === 0,
    comment: tr.to === "returned",
    behalf: needsBehalf(tr.action, can),
    blocked: tr.to === "review" && task.photo === "required" && !task.photos.length ? "photo"
      : tr.from === "todo" && tr.to === "in_progress" && task.waiting.length > 0 && !can.work_manage ? "waiting"
      : null,
  }));
}

// What the client is asked for: approve the plan, accept a task, agree to an extra one
export type ClientNeed = "approvePlan" | "acceptWork" | "agreeExtra";
export const planNeed = (state: WorkState): ClientNeed | null =>
  (state.plan?.state === "proposed" && state.can.work_accept ? "approvePlan" : null);
export function taskNeed(task: WorkTask, plan: WorkPlan | null, can: WorkCan): ClientNeed | null {
  if (plan?.state !== "approved" || !can.work_accept) return null;
  if (task.status === "review") return "acceptWork";
  if (task.status === "proposed" && task.extra) return "agreeExtra";
  return null;
}

// What the task card lets edit, by the rules of the API: the server answers 403 / 409 otherwise
export interface CardRights {
  fact: boolean;       // fact quantities: the installer, while the task is in work
  money: boolean;      // prices, own lines, materials included: the studio, until the client agreed
  photos: boolean;     // upload a photo or a PDF report
  comment: boolean;
  payments: boolean;   // add a payment
  unpay: boolean;      // delete a payment
  manage: boolean;     // title, description, photo rule, assignee, order, "after"
  remove: boolean;     // delete the task
  tick: boolean;       // tick the acceptance criterion (kept on the server)
}

export function cardRights(task: WorkTask, plan: WorkPlan | null, can: WorkCan): CardRights {
  const open = !!plan && plan.state !== "closed";
  const approved = plan?.state === "approved";
  return {
    fact: can.work_do && approved && task.status !== "proposed" && task.status !== "accepted",
    money: open && can.work_manage && task.money_editable,
    photos: approved && (can.work_do || can.work_accept),
    comment: open && (can.work_do || can.work_accept),
    payments: approved && can.work_manage,
    unpay: open && can.work_manage,
    manage: open && can.work_manage,
    remove: open && can.work_manage && (task.status === "todo" || task.status === "proposed")
      && !task.photos.length && !task.payments.length,
    tick: approved && (can.work_do || can.work_accept),
  };
}

// A tick on or off in the sorted list of ticked points (the optimistic state before the answer)
export function ticked(checked: readonly number[], index: number, on: boolean): number[] {
  const rest = checked.filter((i) => i !== index);
  return (on ? [...rest, index] : rest).sort((a, b) => a - b);
}

// --- Merge and move lines (work_manage, while the money of both tasks is open) ------------------

// Where a task may go: other tasks of the plan whose money is still open, in work order; none if
// this one's money is agreed, the plan is closed or the user does not manage it
export function mergeTargets(task: WorkTask, state: WorkState): WorkTask[] {
  const { plan, can } = state;
  if (!plan || plan.state === "closed" || !can.work_manage || !task.money_editable) return [];
  return ordered(state.tasks).filter((t) => t.id !== task.id && t.money_editable);
}

// "Merge with…": shown while the task's money is open; disabled with a reason — a task with photos
// or payments is not merged (409), and there must be somewhere to go
export type MergeBlock = "photos" | "payments" | "noTargets" | null;
export function mergeBlock(task: WorkTask, targets: WorkTask[]): MergeBlock {
  if (task.photos.length) return "photos";
  if (task.payments.length) return "payments";
  return targets.length ? null : "noTargets";
}

// Lines move to another open task; the task may stay empty
export const canMoveLines = (task: WorkTask, targets: WorkTask[]) => targets.length > 0 && task.lines.length > 0;

// --- Order and "after" (work_manage) ------------------------------------------------------------

// Up or down: the position of the neighbour in the shown order (the board may hide another domain).
// PATCH position = the neighbour's puts the task in its place, the server shifts the rest; null —
// already first or last
export function shiftTo(tasks: WorkTask[], id: string, dir: -1 | 1): number | null {
  const list = ordered(tasks);
  const i = list.findIndex((t) => t.id === id);
  const next = i < 0 ? undefined : list[i + dir];
  return next ? next.position : null;
}

// The tasks it goes after: "after" holds ids or keys (the draft links by key); unknown are dropped
export function afterOf(task: WorkTask, tasks: WorkTask[]): WorkTask[] {
  const found = task.after.map((a) => tasks.find((t) => t.id === a || (t.key !== null && t.key === a)));
  return ordered([...new Set(found.filter((t): t is WorkTask => !!t && t.id !== task.id))]);
}

// Number in the plan, 1-based, by work order
export const numberOf = (task: WorkTask, tasks: WorkTask[]) => ordered(tasks).findIndex((t) => t.id === task.id) + 1;

// A photo is deleted by its author until the task is accepted, or by the studio; a photo from an
// access code has no author account, so only the studio deletes it
export function canDeletePhoto(photo: WorkPhoto, task: WorkTask, plan: WorkPlan | null, can: WorkCan, me: string | null): boolean {
  if (!plan || plan.state === "closed") return false;
  if (can.work_manage) return true;
  return !!me && photo.user_id === me && task.status !== "accepted";
}

// Photo tiles: an image the browser can show is a picture; HEIC (most browsers) and PDF are a file tile
const SHOWN = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);
export const isPicture = (p: WorkPhoto) => SHOWN.has(p.content_type.toLowerCase());
export const isPdf = (p: WorkPhoto) => p.content_type.toLowerCase() === "application/pdf";

// The upload limit of the server (records.PHOTO_MAX): a bigger file is refused before sending
export const PHOTO_MAX = 15 * 1024 * 1024;

// The feed of a task: oldest first, as a conversation
export const feedOf = (comments: WorkComment[]) =>
  [...comments].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));

// Progress of the plan for the top of the board: accepted N of M, paid X of Y (shares 0…1)
export interface Progress { accepted: number; tasks: number; paid: number; total: number; done: number; money: number }
export function progressOf(t: WorkTotals): Progress {
  const share = (a: number, b: number) => (b > 0 ? Math.min(1, a / b) : 0);
  return { accepted: t.accepted, tasks: t.tasks, paid: t.paid, total: t.total, done: share(t.accepted, t.tasks), money: share(t.paid, t.total) };
}

// The plan was made from an older model: new work goes as extra tasks
export const modelChanged = (state: WorkState) =>
  !!state.plan && state.plan.model_version !== null && state.model_version !== null && state.model_version !== state.plan.model_version;

// --- Formats ------------------------------------------------------------------------------------

// Money by the plan currency: an ISO code (UAH) — the locale's currency format; anything else
// ("грн", as the estimates write it) — the number and the currency word. Kopecks only when there are
export function money(value: number, currency: string, locale: string): string {
  const digits = Number.isInteger(Math.round(value * 100) / 100) ? 0 : 2;
  const opts = { minimumFractionDigits: digits, maximumFractionDigits: digits };
  if (/^[A-Z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat(locale, { ...opts, style: "currency", currency, currencyDisplay: "narrowSymbol" }).format(value);
    } catch { /* an unknown code: as a word below */ }
  }
  const n = new Intl.NumberFormat(locale, opts).format(value);
  return currency ? `${n} ${currency}` : n;
}

// A quantity: up to two decimals, no trailing zeros
export const qty = (value: number, locale: string) => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);

// A date "YYYY-MM-DD" (payment) is a calendar day, not a moment: no time zone shift
export function day(value: string, locale: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
}

// A moment (comment, photo): date and time in the local zone
export function moment(value: string | null, locale: string): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// Today as "YYYY-MM-DD" in the local zone: the default payment date
export function today(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

// A number typed by a person: comma or dot, spaces; empty — null (as planned / no price);
// not a number or below zero — undefined (refused)
export function parseAmount(text: string): number | null | undefined {
  const s = text.replace(/[\s ]/g, "").replace(",", ".");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

export const fileSize = (bytes: number, locale: string) =>
  `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(bytes / 1024 / 1024)}`;

// A write from a component: the call gets the project key and answers with the whole state,
// which replaces the page's own (widgets/WorkStage/useWork.ts); false — refused, the error is shown
export type WorkRun = (call: (key: string) => Promise<WorkState>) => Promise<boolean>;
