// Work state for Storybook stories of the board, the list and the card: an approved plan with
// tasks in every status, without the API (docs/service-api.md, the GET /work answer)

import type { WorkCan, WorkComment, WorkLine, WorkPlan, WorkState, WorkTask } from "@/shared/types";
import type { WorkRun } from "@/shared/work";

export const STUDIO: WorkCan = { work_do: true, work_accept: true, work_manage: true };
export const INSTALLER: WorkCan = { work_do: true, work_accept: false, work_manage: false };
export const CLIENT: WorkCan = { work_do: false, work_accept: true, work_manage: false };

// Writes do nothing in a story: the buttons are pressed, the state stays
export const noRun: WorkRun = async () => true;

const line = (id: string, kind: WorkLine["kind"], title: string, unit: string, plan_qty: number, price: number | null, fact_qty: number | null = null): WorkLine =>
  ({ id, key: id, kind, title, unit, plan_qty, fact_qty, price, sum: price === null ? null : Math.round((fact_qty ?? plan_qty) * price * 100) / 100 });

const note = (c: Omit<WorkComment, "on_behalf"> & Partial<Pick<WorkComment, "on_behalf">>): WorkComment => ({ on_behalf: null, ...c });

function task(id: string, position: number, over: Partial<WorkTask>): WorkTask {
  const lines = over.lines ?? [];
  const work = lines.filter((l) => l.kind === "work").reduce((s, l) => s + (l.sum ?? 0), 0);
  const material = lines.filter((l) => l.kind === "material").reduce((s, l) => s + (l.sum ?? 0), 0);
  const paid = (over.payments ?? []).reduce((s, p) => s + p.amount, 0);
  const total = work + material;
  return {
    id, key: null, domain: "electrical", position, title: id, description: "", status: "todo", extra: false,
    photo: "optional", result: [], checked: [], after: [], waiting: [], assignee: null, materials_included: true, money_editable: false,
    lines, work_total: work, material_total: material, total, paid, settled: paid >= total && total > 0,
    unpriced: lines.filter((l) => l.price === null).length, photos: [], comments: [], payments: [], ...over,
  };
}

const PETRO = { id: "u-petro", name: "Петро" };
const STUDIO_USER = { id: "u-studio", name: "Ирина (студия)" };

export const TASKS: WorkTask[] = [
  task("chases", 0, {
    key: "electrical.chases", title: "Штробы, проходы, подрозетники", status: "accepted", assignee: PETRO,
    result: ["штробы по трассам проекта, глубина под кабель", "подрозетники установлены по развёрткам"],
    lines: [line("l1", "work", "Штроба в кирпиче", "м", 84, 120, 86.5), line("l2", "work", "Подрозетник", "шт", 42, 60),
            line("l3", "material", "Подрозетник", "шт", 42, 12)],
    photos: [{ id: "ph1", url: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 4 3'%3E%3Crect width='4' height='3' fill='%23b8a98f'/%3E%3Cpath d='M0 2h4' stroke='%23555' stroke-width='.2'/%3E%3C/svg%3E",
               file_name: "IMG_0141.jpg", content_type: "image/jpeg", size: 2_310_000, caption: "кухня, стена у окна", author: "Петро", user_id: "u-petro", created_at: "2026-11-05T09:12:00+00:00" }],
    comments: [
      note({ id: "c1", kind: "status", status: "in_progress", text: "", author: "Петро", user_id: "u-petro", created_at: "2026-11-03T08:00:00+00:00" }),
      note({ id: "c2", kind: "status", status: "review", text: "", author: "Петро", user_id: "u-petro", created_at: "2026-11-05T09:15:00+00:00" }),
      note({ id: "c3", kind: "status", status: "accepted", text: "", author: "Ирина (студия)", user_id: "u-studio",
              on_behalf: { channel: "telegram", note: "фото в чате, «всё ок»" }, created_at: "2026-11-05T18:40:00+00:00" }),
    ],
    payments: [{ id: "pay1", amount: 16020, paid_on: "2026-11-06", note: "", created_at: null }],
  }),
  task("cable", 1, {
    key: "electrical.cable", title: "Прокладка кабеля", status: "returned", photo: "required", assignee: PETRO,
    after: ["electrical.chases"],
    result: ["кабель лежит по трассе и закреплён", "концы промаркированы", "фото трасс до штукатурки"], checked: [0, 2],
    lines: [line("l4", "work", "Прокладка кабеля", "м", 609.4, 34, 615), line("l5", "material", "Кабель ВВГнг-LS 3×2,5", "м", 420, 48),
            line("l6", "material", "Кабель ВВГнг-LS 3×1,5", "м", 189.4, 33)],
    photos: [{ id: "ph2", url: "#", file_name: "IMG_0177.HEIC", content_type: "image/heic", size: 812_345, caption: "", author: "Петро", user_id: "u-petro", created_at: "2026-11-08T10:00:00+00:00" }],
    comments: [
      note({ id: "c4", kind: "status", status: "review", text: "", author: "Петро", user_id: "u-petro", created_at: "2026-11-08T10:05:00+00:00" }),
      note({ id: "c5", kind: "return", status: "returned", text: "В спальне кабель к бра не закреплён, на фото не видно маркировку.", author: "код: Андрей", user_id: null, created_at: "2026-11-08T19:20:00+00:00" }),
      note({ id: "c6", kind: "comment", status: null, text: "Закреплю завтра утром, пришлю фото.", author: "Петро", user_id: "u-petro", created_at: "2026-11-08T19:45:00+00:00" }),
    ],
    payments: [{ id: "pay2", amount: 10000, paid_on: "2026-11-07", note: "аванс", created_at: null }],
  }),
  task("boxes", 2, {
    key: "electrical.boxes", title: "Распаечные коробки", status: "review", assignee: PETRO,
    lines: [line("l7", "work", "Монтаж распаечной коробки", "шт", 14, 150), line("l8", "material", "Коробка распаечная", "шт", 14, 45)],
  }),
  task("board", 3, {
    key: "electrical.board", title: "Установка корпуса щита", status: "in_progress", assignee: STUDIO_USER,
    lines: [line("l9", "work", "Установка корпуса щита", "шт", 1, 1500), line("l10", "material", "Щит ЩРв-36", "шт", 1, null)],
  }),
  task("insulation", 4, {
    key: "electrical.insulation", title: "Замер изоляции", status: "todo", photo: "required",
    waiting: [{ id: "cable", title: "Прокладка кабеля" }, { id: "boxes", title: "Распаечные коробки" }],
    lines: [line("l11", "work", "Замер сопротивления изоляции", "линия", 18, 90)],
  }),
  task("water", 5, {
    key: "plumbing.water", domain: "plumbing", title: "Водопровод", status: "todo", photo: "required",
    lines: [line("l12", "work", "Монтаж трубы PPR", "м", 36, 85), line("l13", "material", "Труба PPR 20", "м", 36, 42)],
  }),
  task("niche", 6, {
    title: "Ниша под роутер в коридоре", domain: "other", status: "proposed", extra: true, money_editable: true,
    description: "Заказчик попросил после утверждения: ниша 300×200 в гипсокартоне.",
    lines: [line("l14", "work", "Ниша в ГКЛ", "шт", 1, 900)],
  }),
];

const sum = (f: (t: WorkTask) => number) => Math.round(TASKS.reduce((s, t) => s + f(t), 0) * 100) / 100;

export const PLAN: WorkPlan = {
  id: "plan", state: "approved", currency: "грн", model_version: 3,
  created_at: "2026-11-01T10:00:00+00:00", approved_at: "2026-11-02T12:00:00+00:00", approved_by: "Ирина (студия)",
  approved_on_behalf: { channel: "phone", note: "звонок 2.11, Андрей" }, closed_at: null,
  totals: {
    work: sum((t) => t.work_total), material: sum((t) => t.material_total), total: sum((t) => t.total), paid: sum((t) => t.paid),
    tasks: TASKS.length, accepted: TASKS.filter((t) => t.status === "accepted").length,
    settled: TASKS.filter((t) => t.settled).length, unpriced: sum((t) => t.unpriced),
  },
};

export function workState(over: Partial<WorkState> = {}): WorkState {
  return { plan: PLAN, tasks: TASKS, draft_available: true, model_version: 3, assignees: [PETRO, STUDIO_USER], can: STUDIO, ...over };
}

// The same tasks before approval: a draft or a plan with the client, everything proposed
export function draftState(state: "draft" | "proposed", can: WorkCan = STUDIO): WorkState {
  const tasks = TASKS.filter((t) => !t.extra).map((t) => ({
    ...t, status: "proposed" as const, money_editable: true, checked: [], photos: [], comments: [], payments: [], paid: 0, settled: false,
  }));
  return workState({ plan: { ...PLAN, state, approved_at: null, approved_by: null, approved_on_behalf: null, totals: { ...PLAN.totals, paid: 0, accepted: 0, settled: 0 } }, tasks, can });
}
