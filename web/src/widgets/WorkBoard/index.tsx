// The studio's board of the "Tasks" tab (work_manage or work_do): on top — the plan state,
// progress (accepted N of M, paid X of Y), the domain switch and the plan buttons; below —
// columns by task status. A plan not approved yet is one column in work order. A tile opens the
// task card (widgets/WorkCard). "Add task" opens a short form: title, description, domain, photo;
// prices and lines are added in the card while the client has not agreed.
// A tile can be dragged to another column (native HTML5 drag, no library): the status changes by
// the same rules as the card's buttons (shared/work.ts, dropTargets) — sent at once, or the card
// opens with the intent (a comment, the client's channel) or with the hint why it is blocked. Drag
// is an enhancement only: a tile stays a button that opens the card, where the keyboard and touch
// users have the same buttons.

import { type DragEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { addWorkTask, setWorkStatus } from "@/shared/api";
import { cx } from "@/shared/cx";
import { locale } from "@/shared/i18n";
import { remember, remembered } from "@/shared/palette";
import type { WorkDomain, WorkPhotoRule, WorkState, WorkStatus, WorkTask } from "@/shared/types";
import {
  behalfText, boardColumns, byColumn, byDomain, canDrag, DOMAIN_FILTERS, domainsOf, dropTargets, modelChanged, money, progressOf,
  splitText, taskNeed, type DomainFilter, type DropTargets, type WorkRun,
} from "@/shared/work";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Heading } from "@/ui/Heading";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";
import { TextArea } from "@/ui/TextArea";
import { TextField } from "@/ui/TextField";
import { WorkPlanActions } from "@/widgets/WorkPlanActions";
import css from "./WorkBoard.module.scss";

interface Props {
  state: WorkState;
  run: WorkRun;
  busy: boolean;
  open: string | null;               // the task whose card is open
  onOpen: (task: string, intent?: WorkStatus) => void;   // intent: a drop that the card finishes
}

// What is being dragged and where it may go
interface Drag { id: string; targets: DropTargets }

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

  const [drag, setDrag] = useState<Drag | null>(null);
  const [over, setOver] = useState<WorkStatus | null>(null);     // the column under the dragged tile
  const [moving, setMoving] = useState<string | null>(null);     // the tile whose status is being sent
  const endDrag = () => { setDrag(null); setOver(null); };
  const dropOn = (s: WorkStatus) => {
    if (!drag) return;
    const { id, targets } = drag;
    endDrag();
    const kind = targets[s];
    if (!kind) return;
    if (kind === "ok") {
      setMoving(id);
      void run((key) => setWorkStatus(key, id, s)).finally(() => setMoving(null));
    } else {
      onOpen(id, s);
    }
  };

  return (
    <div className={css.board}>
      <header className={css.head}>
        <div className={css.title}>
          <Heading level={1}>{t("work.title")}</Heading>
          <span className={css.state} data-state={plan.state}>{t(`work.plan.${plan.state}`)}</span>
          {plan.approved_on_behalf && <span className={css.behalf}>{behalfText(plan.approved_on_behalf, "plan")}</span>}
        </div>
        {working && <Progress state={state} />}
        {!working && (
          <Text tone="muted" className={css.lead}>
            {plan.state === "draft" ? t("work.draftLead") : t("work.proposedLead")}{" "}
            <b>{money(plan.totals.total, plan.currency, locale())}</b>
          </Text>
        )}
        <Text size="small" tone="muted" className={css.split}>{splitText(plan.totals.work, plan.totals.material, plan.currency)}</Text>
        {modelChanged(state) && (
          <Text size="small" tone="major">{t("work.modelChanged", { plan: plan.model_version, now: state.model_version })}</Text>
        )}
        <div className={css.tools}>
          {both && (
            <SegmentedControl label={t("work.filter")} value={filter} onChange={pick}
                              options={DOMAIN_FILTERS.map((f) => ({ value: f, label: t(`work.domain.${f}`) }))} />
          )}
          <WorkPlanActions state={state} run={run} busy={busy} onAdd={() => setAdding(true)} />
        </div>
        {adding && <TaskForm run={run} busy={busy} extra={plan.state === "approved"} onDone={() => setAdding(false)} />}
      </header>
      <div className={cx(css.columns, columns.length === 1 && css.single)}
           style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(220px, 1fr))` }}>
        {columns.map((s) => {
          const kind = drag ? drag.targets[s] : null;
          return (
            <section key={s} className={css.column} aria-label={t(`work.status.${s}`)}
                     data-drop={kind ?? undefined} data-over={kind && over === s ? "" : undefined}
                     onDragEnter={(e) => { if (kind) e.preventDefault(); }}
                     onDragOver={(e) => {
                       if (!kind) return;
                       e.preventDefault();
                       if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
                       if (over !== s) setOver(s);
                     }}
                     onDragLeave={(e) => {
                       if (over === s && !(e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget))) setOver(null);
                     }}
                     onDrop={(e) => { e.preventDefault(); dropOn(s); }}>
              <h2 className={css.columnTitle}>
                <span className={css.dot} data-status={s} aria-hidden="true" />
                {t(`work.status.${s}`)}
                <span className={css.count}>{grouped[s].length}</span>
              </h2>
              <div className={css.tiles}>
                {grouped[s].map((task) => (
                  <Tile key={task.id} task={task} state={state} open={task.id === open} domain={!both || filter === "all"}
                        dragging={drag?.id === task.id} moving={moving === task.id} drag={!busy && !moving}
                        onOpen={() => onOpen(task.id)}
                        onDragStart={() => setDrag({ id: task.id, targets: dropTargets(task, plan, state.can) })} onDragEnd={endDrag} />
                ))}
                {!grouped[s].length && <Text size="small" tone="muted" className={css.none}>{t("work.columnEmpty")}</Text>}
              </div>
            </section>
          );
        })}
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

// A task tile: title, what it waits for, who does it, sum, photos and payment. Dragged only by
// a user who has a transition for it (canDrag); the dragged one fades, the one being sent waits
function Tile({ task, state, open, domain, dragging, moving, drag, onOpen, onDragStart, onDragEnd }: {
  task: WorkTask; state: WorkState; open: boolean; domain: boolean; dragging: boolean; moving: boolean; drag: boolean;
  onOpen: () => void; onDragStart: () => void; onDragEnd: () => void;
}) {
  const { t } = useTranslation();
  const plan = state.plan!;
  const need = taskNeed(task, plan, state.can);
  const draggable = drag && canDrag(task, plan, state.can);
  const start = (e: DragEvent) => {
    // Firefox starts a drag only with data set; the id itself travels in the board's state
    e.dataTransfer?.setData("text/plain", task.id);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
    onDragStart();
  };
  return (
    <Card as="button" type="button" padding="sm" interactive className={cx(css.tile, open && css.open, dragging && css.dragging, moving && css.moving)}
          aria-pressed={open} aria-busy={moving || undefined} draggable={draggable} onDragStart={draggable ? start : undefined} onDragEnd={onDragEnd}
          onClick={onOpen}>
      <span className={css.tags}>
        {domain && <Tag>{t(`work.domain.${task.domain}`)}</Tag>}
        {task.extra && <Tag tone="major">{t("work.extra")}</Tag>}
        {need && <Tag className={css.need}>{t(`work.need.${need}`)}</Tag>}
      </span>
      <b className={css.name}>{task.title}</b>
      {task.waiting.length > 0 && task.status !== "accepted" && (
        <span className={css.waiting}>{t("work.waiting", { list: task.waiting.map((w) => w.title).join(", ") })}</span>
      )}
      <span className={css.meta}>
        <span className={cx(!task.assignee && "muted")}>{task.assignee?.name ?? t("work.nobody")}</span>
        <span className={css.sum}>{money(task.total, plan.currency, locale())}</span>
      </span>
      <span className={css.split}>{splitText(task.work_total, task.material_total, plan.currency, task.materials_included)}</span>
      <span className={css.marks}>
        {task.photo === "required" && !task.photos.length && <span className={css.want}>{t("work.photoRequired")}</span>}
        {task.photos.length > 0 && <span>{t("work.photosN", { n: task.photos.length })}</span>}
        {task.unpriced > 0 && <span className={css.want}>{t("work.unpriced", { n: task.unpriced })}</span>}
        {task.settled && task.total > 0 && <span className={css.paid}>{t("work.paidMark")}</span>}
        {!task.settled && task.paid > 0 && <span>{t("work.paidPart", { paid: money(task.paid, plan.currency, locale()) })}</span>}
      </span>
    </Card>
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
    <Card as="form" className={css.form} onSubmit={submit}>
      <Heading level={2} size="subheading">{t("work.form.title")}</Heading>
      {extra && <Text size="small" tone="major">{t("work.form.extraNote")}</Text>}
      <TextField label={t("work.form.name")} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required autoFocus />
      <TextArea label={t("work.form.description")} value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={4000} />
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
        <Button type="submit" variant="primary" disabled={busy || !title.trim()}>{t("work.form.add")}</Button>
        <Button onClick={onDone}>{t("work.form.cancel")}</Button>
      </div>
    </Card>
  );
}
