// The studio's board of the "Tasks" tab (work_manage or work_do): on top — the plan state,
// progress (accepted N of M, paid X of Y), the domain switch and the plan buttons; below —
// columns by task status. A plan not approved yet is one column in work order. A tile opens the
// task card (widgets/WorkCard). "Add task" opens a short form: title, description, domain, photo;
// prices and lines are added in the card while the client has not agreed.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { addWorkTask } from "@/shared/api";
import { cx } from "@/shared/cx";
import { locale } from "@/shared/i18n";
import { remember, remembered } from "@/shared/palette";
import ui from "@/shared/styles/ui.module.scss";
import type { WorkDomain, WorkPhotoRule, WorkState, WorkTask } from "@/shared/types";
import {
  behalfText, boardColumns, byColumn, byDomain, DOMAIN_FILTERS, domainsOf, modelChanged, money, progressOf, taskNeed,
  type DomainFilter, type WorkRun,
} from "@/shared/work";
import { WorkPlanActions } from "@/widgets/WorkPlanActions";
import css from "./WorkBoard.module.scss";

interface Props {
  state: WorkState;
  run: WorkRun;
  busy: boolean;
  open: string | null;               // the task whose card is open
  onOpen: (task: string) => void;
}

const savedFilter = (): DomainFilter => {
  const v = remembered("work-domain");
  return (DOMAIN_FILTERS as readonly string[]).includes(v ?? "") ? (v as DomainFilter) : "all";
};

export function WorkBoard({ state, run, busy, open, onOpen }: Props) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<DomainFilter>(savedFilter);
  const [adding, setAdding] = useState(false);
  const plan = state.plan!;
  const both = domainsOf(state.tasks).filter((d) => d !== "other").length > 1;
  const shown = byDomain(state.tasks, both ? filter : "all");
  const columns = boardColumns(plan, state.tasks);
  const grouped = byColumn(shown);
  const pick = (f: DomainFilter) => { setFilter(f); remember("work-domain", f); };
  const working = plan.state === "approved" || plan.state === "closed";

  return (
    <div className={css.board}>
      <header className={css.head}>
        <div className={css.title}>
          <h1>{t("work.title")}</h1>
          <span className={css.state} data-state={plan.state}>{t(`work.plan.${plan.state}`)}</span>
          {plan.approved_on_behalf && <span className={css.behalf}>{behalfText(plan.approved_on_behalf, "plan")}</span>}
        </div>
        {working && <Progress state={state} />}
        {!working && (
          <p className={css.lead}>
            {plan.state === "draft" ? t("work.draftLead") : t("work.proposedLead")}{" "}
            <b>{money(plan.totals.total, plan.currency, locale())}</b>
          </p>
        )}
        {modelChanged(state) && (
          <p className={css.note}>{t("work.modelChanged", { plan: plan.model_version, now: state.model_version })}</p>
        )}
        <div className={css.tools}>
          {both && (
            <div className={ui.segmented} role="radiogroup" aria-label={t("work.filter")}>
              {DOMAIN_FILTERS.map((f) => (
                <button key={f} role="radio" aria-checked={f === filter} className={cx(f === filter && ui.on)}
                        onClick={() => pick(f)}>{t(`work.domain.${f}`)}</button>
              ))}
            </div>
          )}
          <WorkPlanActions state={state} run={run} busy={busy} onAdd={() => setAdding(true)} />
        </div>
        {adding && <TaskForm run={run} busy={busy} extra={plan.state === "approved"} onDone={() => setAdding(false)} />}
      </header>
      <div className={cx(css.columns, columns.length === 1 && css.single)}
           style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(220px, 1fr))` }}>
        {columns.map((s) => (
          <section key={s} className={css.column} aria-label={t(`work.status.${s}`)}>
            <h2>
              <span className={css.dot} data-status={s} aria-hidden="true" />
              {t(`work.status.${s}`)}
              <span className={css.count}>{grouped[s].length}</span>
            </h2>
            <div className={css.tiles}>
              {grouped[s].map((task) => (
                <Tile key={task.id} task={task} state={state} open={task.id === open} domain={!both || filter === "all"}
                      onOpen={() => onOpen(task.id)} />
              ))}
              {!grouped[s].length && <p className={css.none}>{t("work.columnEmpty")}</p>}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

// Accepted N of M, paid X of Y: two thin bars
function Progress({ state }: { state: WorkState }) {
  const { t } = useTranslation();
  const plan = state.plan!;
  const p = progressOf(plan.totals);
  const m = (v: number) => money(v, plan.currency, locale());
  return (
    <div className={css.progress}>
      <div>
        <span>{t("work.progress.accepted", { n: p.accepted, m: p.tasks })}</span>
        <span className={css.bar} role="progressbar" aria-valuemin={0} aria-valuemax={p.tasks} aria-valuenow={p.accepted}>
          <i style={{ width: `${p.done * 100}%` }} />
        </span>
      </div>
      <div>
        <span>{t("work.progress.paid", { paid: m(p.paid), total: m(p.total) })}</span>
        <span className={css.bar} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p.money * 100)}>
          <i style={{ width: `${p.money * 100}%` }} />
        </span>
      </div>
    </div>
  );
}

// A task tile: title, what it waits for, who does it, sum, photos and payment
function Tile({ task, state, open, domain, onOpen }: { task: WorkTask; state: WorkState; open: boolean; domain: boolean; onOpen: () => void }) {
  const { t } = useTranslation();
  const plan = state.plan!;
  const need = taskNeed(task, plan, state.can);
  return (
    <button type="button" className={cx(css.tile, open && css.open)} aria-pressed={open} onClick={onOpen}>
      <span className={css.tags}>
        {domain && <span className={css.tag}>{t(`work.domain.${task.domain}`)}</span>}
        {task.extra && <span className={cx(css.tag, css.extra)}>{t("work.extra")}</span>}
        {need && <span className={cx(css.tag, css.need)}>{t(`work.need.${need}`)}</span>}
      </span>
      <b className={css.name}>{task.title}</b>
      {task.waiting.length > 0 && task.status !== "accepted" && (
        <span className={css.waiting}>{t("work.waiting", { list: task.waiting.map((w) => w.title).join(", ") })}</span>
      )}
      <span className={css.meta}>
        <span className={cx(!task.assignee && "muted")}>{task.assignee?.name ?? t("work.nobody")}</span>
        <span className={css.sum}>{money(task.total, plan.currency, locale())}</span>
      </span>
      <span className={css.marks}>
        {task.photo === "required" && !task.photos.length && <span className={css.want}>{t("work.photoRequired")}</span>}
        {task.photos.length > 0 && <span>{t("work.photosN", { n: task.photos.length })}</span>}
        {task.unpriced > 0 && <span className={css.want}>{t("work.unpriced", { n: task.unpriced })}</span>}
        {task.settled && task.total > 0 && <span className={css.paid}>{t("work.paidMark")}</span>}
        {!task.settled && task.paid > 0 && <span>{t("work.paidPart", { paid: money(task.paid, plan.currency, locale()) })}</span>}
      </span>
    </button>
  );
}

// "Add task": after approval it goes as extra work the client agrees to
function TaskForm({ run, busy, extra, onDone }: { run: WorkRun; busy: boolean; extra: boolean; onDone: () => void }) {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [domain, setDomain] = useState<WorkDomain>("electrical");
  const [photo, setPhoto] = useState<WorkPhotoRule>("optional");
  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!title.trim()) return;
    const ok = await run((key) => addWorkTask(key, { title: title.trim(), description: description.trim(), domain, photo }));
    if (ok) onDone();
  };
  return (
    <form className={css.form} onSubmit={submit}>
      <h2>{t("work.form.title")}</h2>
      {extra && <p className={css.note}>{t("work.form.extraNote")}</p>}
      <label>
        <span>{t("work.form.name")}</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required autoFocus />
      </label>
      <label>
        <span>{t("work.form.description")}</span>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={4000} />
      </label>
      <div className={css.formRow}>
        <label>
          <span>{t("work.form.domain")}</span>
          <select value={domain} onChange={(e) => setDomain(e.target.value as WorkDomain)}>
            {(["electrical", "plumbing", "other"] as const).map((d) => <option key={d} value={d}>{t(`work.domain.${d}`)}</option>)}
          </select>
        </label>
        <label>
          <span>{t("work.card.photoRuleLabel")}</span>
          <select value={photo} onChange={(e) => setPhoto(e.target.value as WorkPhotoRule)}>
            {(["required", "optional", "none"] as const).map((p) => <option key={p} value={p}>{t(`work.photoRule.${p}`)}</option>)}
          </select>
        </label>
      </div>
      <div className={css.formButtons}>
        <button type="submit" className={css.primary} disabled={busy || !title.trim()}>{t("work.form.add")}</button>
        <button type="button" onClick={onDone}>{t("work.form.cancel")}</button>
      </div>
    </form>
  );
}
