// Task card of the "Tasks" tab: over the side panel, like the header drawer; on a narrow screen —
// the whole screen. Status and the buttons of the role and status (shared/work.ts, statusButtons:
// "Return" asks for a comment, "Hand in" waits for a photo when one is required), what it waits
// for, assignee, order and "after" (widgets/WorkOrder), description, acceptance criterion as a
// checklist (ticks are kept), lines plan / fact / price / sum (the studio moves selected lines to
// another task), totals, "Merge with…" (widgets/WorkMerge), photos with upload, the feed (with the
// client's channel when the studio acted for the client), payments. The client's actions by the
// studio ask "how did the client confirm?" first (widgets/WorkConfirm). Every write goes through run
// and the whole state comes back (shared/api.ts). Titles, lines and criteria are in the project language.

import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  addWorkComment, addWorkLine, addWorkPayment, deleteWorkPayment, deleteWorkPhoto, deleteWorkTask, editWorkLine,
  editWorkTask, moveWorkLines, setWorkCheck, setWorkStatus, uploadWorkPhoto, WorkError,
} from "@/shared/api";
import { cx } from "@/shared/cx";
import { locale } from "@/shared/i18n";
import ui from "@/shared/styles/ui.module.scss";
import type { WorkLine, WorkOnBehalf, WorkPhotoRule, WorkState, WorkTask } from "@/shared/types";
import {
  behalfText, canDeletePhoto, canMoveLines, cardRights, day, feedOf, fileSize, isPdf, isPicture, mergeTargets, moment,
  money, numberOf, parseAmount, PHOTO_MAX, qty, statusButtons, taskNeed, ticked, today, type StatusButton, type WorkRun,
} from "@/shared/work";
import { Select } from "@/ui/Select";
import { WorkConfirm } from "@/widgets/WorkConfirm";
import { WorkMerge } from "@/widgets/WorkMerge";
import { WorkOrder } from "@/widgets/WorkOrder";
import { WorkStatusBadge } from "@/widgets/WorkStatusBadge";
import css from "./WorkCard.module.scss";

interface Props {
  task: WorkTask;
  state: WorkState;
  run: WorkRun;
  busy: boolean;
  error: string | null;       // the last refusal of the server
  onError: () => void;        // the error was read: hide it
  me: string | null;          // the logged-in user id: own photos are deleted by their author
  onClose: () => void;
  onOpen?: (task: string) => void;  // open another task: the target after a merge
}

export function WorkCard({ task, state, run, busy, error, onError, me, onClose, onOpen }: Props) {
  const { t } = useTranslation();
  const plan = state.plan;
  const rights = cardRights(task, plan, state.can);
  const need = taskNeed(task, plan, state.can);
  const targets = mergeTargets(task, state);
  const cur = plan?.currency ?? "";
  const m = (v: number) => money(v, cur, locale());

  // Esc closes the card, unless a field is being typed in
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || (e.target instanceof HTMLElement && e.target.closest("input, textarea, select, [role=listbox]"))) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const remove = () => {
    if (confirm(t("work.card.removeAsk", { title: task.title }))) void run((key) => deleteWorkTask(key, task.id)).then((ok) => ok && onClose());
  };

  return (
    <section className={css.card} role="dialog" aria-label={task.title}>
      <header className={ui.panelHead}>
        <h2>{t("work.card.heading")}</h2>
        <button type="button" onClick={onClose} aria-label={t("common.closeEsc")} title={t("common.closeEsc")}>×</button>
      </header>
      <div className={cx(ui.panelBody, css.body)}>
        <div className={css.top}>
          <WorkStatusBadge status={task.status} />
          <span className={css.tag}>{t(`work.domain.${task.domain}`)}</span>
          {task.extra && <span className={cx(css.tag, css.extra)}>{t("work.extra")}</span>}
        </div>
        <Heading task={task} run={run} busy={busy} editable={rights.manage} />

        {error && (
          <div className={css.error} role="alert">
            <span>{error}</span>
            <button type="button" onClick={onError} aria-label={t("common.close")}>×</button>
          </div>
        )}
        {need && <p className={css.need}>{t(`work.need.${need}`)}</p>}
        <StatusButtons task={task} buttons={statusButtons(task, plan, state.can)} run={run} busy={busy} />
        {task.waiting.length > 0 && task.status !== "accepted" && (
          <p className={css.waiting}>{t("work.waiting", { list: task.waiting.map((w) => w.title).join(", ") })}</p>
        )}

        <dl className={css.pairs}>
          <dt>{t("work.assignee")}</dt>
          <dd>
            {rights.manage && state.assignees.length > 0 ? (
              <Select label={t("work.assignee")} value={task.assignee?.id ?? ""}
                      options={[{ value: "", label: t("work.nobody") },
                                ...state.assignees.map((a) => ({ value: a.id, label: a.name }))]}
                      onChange={(v) => { if (!busy) void run((key) => editWorkTask(key, task.id, { assignee_id: v || null })); }} />
            ) : (task.assignee?.name ?? <span className="muted">{t("work.nobody")}</span>)}
          </dd>
          <dt>{t("work.card.photoRuleLabel")}</dt>
          <dd>
            {rights.manage ? (
              <select className={css.inline} value={task.photo} disabled={busy}
                      onChange={(e) => void run((key) => editWorkTask(key, task.id, { photo: e.target.value as WorkPhotoRule }))}>
                {(["required", "optional", "none"] as const).map((p) => <option key={p} value={p}>{t(`work.photoRule.${p}`)}</option>)}
              </select>
            ) : t(`work.photoRule.${task.photo}`)}
          </dd>
        </dl>
        <WorkOrder task={task} state={state} run={run} busy={busy} editable={rights.manage} />

        {task.result.length > 0 && (
          <>
            <h3>{t("work.card.result")}</h3>
            <Checklist key={task.id} task={task} run={run} busy={busy} editable={rights.tick}
                       later={!rights.tick && (plan?.state === "draft" || plan?.state === "proposed") && (state.can.work_do || state.can.work_accept)} />
          </>
        )}

        <h3>{t("work.card.lines")}</h3>
        <Lines task={task} state={state} currency={cur} run={run} busy={busy} fact={rights.fact} price={rights.money}
               move={rights.money && canMoveLines(task, targets) ? targets : []} />
        {rights.money && <LineForm task={task} run={run} busy={busy} />}
        <dl className={css.totals}>
          <dt>{t("work.card.work")}</dt><dd>{m(task.work_total)}</dd>
          <dt>
            {t("work.card.materials")}
            {task.material_total > 0 && <span className="muted"> · {t("work.card.materialsMock")}</span>}
            {!task.materials_included && <span className="muted"> · {t("work.card.notIncluded")}</span>}
          </dt>
          <dd className={cx(!task.materials_included && "muted")}>{m(task.material_total)}</dd>
          <dt className={css.grand}>{t("work.card.total")}</dt><dd className={css.grand}>{m(task.total)}</dd>
          {(task.paid > 0 || rights.payments) && (
            <>
              <dt>{t("work.card.paid")}</dt>
              <dd className={cx(task.settled && task.total > 0 && css.ok)}>{m(task.paid)}</dd>
            </>
          )}
        </dl>
        {task.unpriced > 0 && <p className={css.warn}>{t("work.card.unpricedNote", { n: task.unpriced })}</p>}
        {rights.money && (
          <label className={css.check}>
            <input type="checkbox" checked={task.materials_included} disabled={busy}
                   onChange={(e) => void run((key) => editWorkTask(key, task.id, { materials_included: e.target.checked }))} />
            {t("work.card.materialsIncluded")}
          </label>
        )}

        <h3>{t("work.card.photos")}</h3>
        <Photos task={task} state={state} run={run} busy={busy} me={me} upload={rights.photos} onError={onError} />

        <h3>{t("work.card.feed")}</h3>
        <Feed task={task} run={run} busy={busy} write={rights.comment} />

        {(task.payments.length > 0 || rights.payments) && (
          <>
            <h3>{t("work.card.payments")}</h3>
            <Payments task={task} currency={cur} run={run} busy={busy} add={rights.payments} remove={rights.unpay} />
          </>
        )}

        {rights.money && <WorkMerge task={task} state={state} run={run} busy={busy} onMerged={(into) => (onOpen ? onOpen(into) : onClose())} />}
        {rights.remove && (
          <button type="button" className={css.danger} disabled={busy} onClick={remove}>{t("work.card.remove")}</button>
        )}
      </div>
    </section>
  );
}

// Title and description; the studio edits them in place
function Heading({ task, run, busy, editable }: { task: WorkTask; run: WorkRun; busy: boolean; editable: boolean }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(task.title);
  const [description, setDescription] = useState(task.description);
  useEffect(() => { setEditing(false); }, [task.id]);
  const start = () => { setTitle(task.title); setDescription(task.description); setEditing(true); };
  const save = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!title.trim()) return;
    const ok = await run((key) => editWorkTask(key, task.id, { title: title.trim(), description: description.trim() }));
    if (ok) setEditing(false);
  };
  if (editing) {
    return (
      <form className={css.edit} onSubmit={save}>
        <label><span>{t("work.form.name")}</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required autoFocus /></label>
        <label><span>{t("work.form.description")}</span>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={4000} /></label>
        <div className={css.row}>
          <button type="submit" className={css.primary} disabled={busy || !title.trim()}>{t("work.card.save")}</button>
          <button type="button" onClick={() => setEditing(false)}>{t("work.form.cancel")}</button>
        </div>
      </form>
    );
  }
  return (
    <div className={css.heading}>
      <h1>{task.title}</h1>
      {task.description && <p className={css.description}>{task.description}</p>}
      {editable && <button type="button" className={css.link} onClick={start}>{t("work.card.edit")}</button>}
    </div>
  );
}

// Status buttons: the first is the main one; "Return" opens a comment field first; a blocked one
// is disabled and says why. The studio doing the client's step (agree, accept, return) is asked
// the client's channel before sending (WorkConfirm); the dialog closes after the answer either way —
// a refusal is said in the card
function StatusButtons({ task, buttons, run, busy }: { task: WorkTask; buttons: StatusButton[]; run: WorkRun; busy: boolean }) {
  const { t } = useTranslation();
  const [returning, setReturning] = useState(false);
  const [comment, setComment] = useState("");
  const [asking, setAsking] = useState<{ button: StatusButton; comment?: string } | null>(null);
  const hintId = useId();
  useEffect(() => { setReturning(false); setComment(""); setAsking(null); }, [task.id, task.status]);
  if (!buttons.length) return null;
  const blocked = buttons.find((b) => b.blocked);
  const send = (b: StatusButton, text?: string, onBehalf?: WorkOnBehalf) => run((key) => setWorkStatus(key, task.id, b.to, text, onBehalf));
  const press = (b: StatusButton) => {
    if (b.comment) { setReturning(true); return; }
    if (b.behalf) { setAsking({ button: b }); return; }
    void send(b);
  };
  const sendBack = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!comment.trim()) return;
    const ret = buttons.find((b) => b.comment)!;
    if (ret.behalf) { setAsking({ button: ret, comment: comment.trim() }); return; }
    if (await send(ret, comment.trim())) setReturning(false);
  };
  const confirmed = async (onBehalf: WorkOnBehalf) => {
    if (!asking) return;
    const ok = await send(asking.button, asking.comment, onBehalf);
    setAsking(null);
    if (ok && asking.comment !== undefined) setReturning(false);
  };
  return (
    <div className={css.status}>
      <div className={css.row}>
        {buttons.map((b) => (
          <button key={b.to} type="button" className={cx(b.primary && css.primary, b.comment && returning && css.pressed)}
                  disabled={busy || !!b.blocked} aria-describedby={b.blocked ? hintId : undefined} onClick={() => press(b)}>
            {t(`work.btn.${b.action}`)}
          </button>
        ))}
      </div>
      {blocked && (
        <p id={hintId} className={css.hint}>
          {blocked.blocked === "photo"
            ? t("work.card.blockedPhoto")
            : t("work.card.blockedWaiting", { list: task.waiting.map((w) => w.title).join(", ") })}
        </p>
      )}
      {returning && (
        <form className={css.returnForm} onSubmit={sendBack}>
          <label>
            <span>{t("work.card.returnComment")}</span>
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} maxLength={4000} required autoFocus />
          </label>
          <div className={css.row}>
            <button type="submit" className={css.primary} disabled={busy || !comment.trim()}>{t("work.card.returnSend")}</button>
            <button type="button" onClick={() => setReturning(false)}>{t("work.form.cancel")}</button>
          </div>
        </form>
      )}
      {asking && (
        <WorkConfirm action={t(`work.btn.${asking.button.action}`)} detail={task.title} busy={busy}
                     onCancel={() => setAsking(null)} onConfirm={(ob) => void confirmed(ob)} />
      )}
    </div>
  );
}

// The acceptance criterion as checkboxes, kept on the server (PATCH …/checks): the installer and the
// client tick it in an approved plan, otherwise it is read-only. A tick shows at once and is then
// replaced by the answer (a refusal brings the old state back)
function Checklist({ task, run, busy, editable, later }: { task: WorkTask; run: WorkRun; busy: boolean; editable: boolean; later: boolean }) {
  const { t } = useTranslation();
  const saved = task.checked.join(",");
  const [shown, setShown] = useState<number[]>(task.checked);
  useEffect(() => setShown(task.checked), [saved]);  // the answer replaces the optimistic ticks
  const toggle = async (i: number, on: boolean) => {
    setShown((prev) => ticked(prev, i, on));
    if (!(await run((key) => setWorkCheck(key, task.id, i, on)))) setShown(task.checked);
  };
  return (
    <>
      <ul className={css.checklist}>
        {task.result.map((x, i) => {
          const on = shown.includes(i);
          return (
            <li key={i}>
              <label className={cx(on && css.ticked, !editable && css.readonly)}>
                <input type="checkbox" checked={on} disabled={!editable || busy} onChange={(e) => void toggle(i, e.target.checked)} />
                <span>{x}</span>
              </label>
            </li>
          );
        })}
      </ul>
      {later && <p className={cx(css.later, "muted small")}>{t("work.card.checksLater")}</p>}
    </>
  );
}

// Lines: name | plan | fact | price | sum. Fact is typed by the installer (empty — as planned),
// price by the studio while the client has not agreed (empty — no price). While the money of this
// task and others is open, the studio ticks lines and moves them to another task (move — targets)
function Lines({ task, state, currency, run, busy, fact, price, move }: {
  task: WorkTask; state: WorkState; currency: string; run: WorkRun; busy: boolean; fact: boolean; price: boolean; move: WorkTask[];
}) {
  const { t } = useTranslation();
  const loc = locale();
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [to, setTo] = useState("");
  const ids = task.lines.map((l) => l.id).join(",");
  useEffect(() => setPicked(new Set()), [ids]);  // the lines changed (moved away, merged): nothing is picked
  if (!task.lines.length) return <p className="muted small">{t("work.card.noLines")}</p>;
  const save = (line: WorkLine, edit: { fact_qty?: number | null; price?: number | null }) =>
    run((key) => editWorkLine(key, task.id, line.id, edit));
  const selectable = move.length > 0;
  const cols = selectable ? 6 : 5;
  const toggle = (id: string) => setPicked((prev) => {
    const next = new Set(prev);
    if (!next.delete(id)) next.add(id);
    return next;
  });
  const target = move.find((x) => x.id === to) ?? move[0];
  const send = () => {
    const lineIds = task.lines.filter((l) => picked.has(l.id)).map((l) => l.id);
    if (target && lineIds.length) void run((key) => moveWorkLines(key, task.id, lineIds, target.id));
  };
  return (
    <>
      <div className={css.scroll}>
        <table className={css.lines}>
          <thead>
            <tr>
              {selectable && <th aria-hidden="true" />}
              <th>{t("work.card.col.name")}</th>
              <th className={css.num}>{t("work.card.col.plan")}</th>
              <th className={css.num}>{t("work.card.col.fact")}</th>
              <th className={css.num}>{t("work.card.col.price")}</th>
              <th className={css.num}>{t("work.card.col.sum")}</th>
            </tr>
          </thead>
          <tbody>
            {(["work", "material"] as const).map((kind) => {
              const rows = task.lines.filter((l) => l.kind === kind);
              if (!rows.length) return null;
              return [
                <tr key={kind} className={css.section}><td colSpan={cols}>{t(`work.card.kind.${kind}`)}</td></tr>,
                ...rows.map((l) => (
                  <tr key={l.id} className={cx(l.price === null && css.unpriced, picked.has(l.id) && css.picked)}>
                    {selectable && (
                      <td className={css.pick}>
                        <input type="checkbox" checked={picked.has(l.id)} onChange={() => toggle(l.id)}
                               aria-label={t("work.card.selectLine", { name: l.title })} />
                      </td>
                    )}
                    <td>{l.title}</td>
                    <td className={css.num}>{qty(l.plan_qty, loc)}&nbsp;{l.unit}</td>
                    <td className={css.num}>
                      {fact ? (
                        <NumberCell value={l.fact_qty} placeholder={qty(l.plan_qty, loc)} label={t("work.card.factOf", { name: l.title })}
                                    disabled={busy} onSave={(v) => save(l, { fact_qty: v })} />
                      ) : l.fact_qty === null ? <span className="muted">—</span> : qty(l.fact_qty, loc)}
                    </td>
                    <td className={css.num}>
                      {price ? (
                        <NumberCell value={l.price} placeholder="—" label={t("work.card.priceOf", { name: l.title })}
                                    disabled={busy} onSave={(v) => save(l, { price: v })} />
                      ) : l.price === null ? <span className="muted">{t("work.card.noPrice")}</span> : money(l.price, currency, loc)}
                    </td>
                    <td className={css.num}>{l.sum === null ? <span className="muted">—</span> : money(l.sum, currency, loc)}</td>
                  </tr>
                )),
              ];
            })}
          </tbody>
        </table>
      </div>
      {selectable && picked.size > 0 && (
        <div className={css.moveBar}>
          <span>{t("work.card.selected", { n: picked.size })}</span>
          <span className={css.label}>{t("work.card.moveTo")}</span>
          <Select label={t("work.card.moveTo")} value={target?.id ?? ""} onChange={setTo}
                  options={move.map((x) => ({ value: x.id, label: `${numberOf(x, state.tasks)}. ${x.title}` }))} />
          <button type="button" className={css.primary} disabled={busy || !target} onClick={send}>{t("work.card.moveGo")}</button>
        </div>
      )}
    </>
  );
}

// A number field saved when it loses focus or on Enter, only if it changed; a wrong number stays
// red and is not sent
function NumberCell({ value, placeholder, label, disabled, onSave }: {
  value: number | null; placeholder: string; label: string; disabled: boolean; onSave: (v: number | null) => Promise<boolean>;
}) {
  const shown = value === null ? "" : String(value);
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
  const parsed = parseAmount(text);
  const commit = () => {
    if (parsed === undefined || parsed === value) return;
    void onSave(parsed).then((ok) => { if (!ok) setText(shown); });
  };
  return (
    <input className={cx(css.cell, parsed === undefined && css.bad)} inputMode="decimal" value={text} placeholder={placeholder}
           aria-label={label} aria-invalid={parsed === undefined} disabled={disabled}
           onChange={(e) => setText(e.target.value)} onBlur={commit}
           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}

// The studio's own line while the sum is not agreed
function LineForm({ task, run, busy }: { task: WorkTask; run: WorkRun; busy: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<"work" | "material">("work");
  const [unit, setUnit] = useState("");
  const [amount, setAmount] = useState("1");
  const [price, setPrice] = useState("");
  const n = parseAmount(amount), p = parseAmount(price);
  const valid = !!title.trim() && typeof n === "number" && p !== undefined;
  if (!open) return <button type="button" className={css.link} onClick={() => setOpen(true)}>+ {t("work.card.addLine")}</button>;
  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!valid) return;
    const ok = await run((key) => addWorkLine(key, task.id, { title: title.trim(), kind, unit: unit.trim(), qty: n as number, price: p }));
    if (ok) { setOpen(false); setTitle(""); setUnit(""); setAmount("1"); setPrice(""); }
  };
  return (
    <form className={css.lineForm} onSubmit={submit}>
      <label className={css.wide}><span>{t("work.form.name")}</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} required autoFocus /></label>
      <label><span>{t("work.card.lineKind")}</span>
        <select value={kind} onChange={(e) => setKind(e.target.value as "work" | "material")}>
          <option value="work">{t("work.card.kind.work")}</option>
          <option value="material">{t("work.card.kind.material")}</option>
        </select></label>
      <label><span>{t("work.card.lineUnit")}</span><input value={unit} onChange={(e) => setUnit(e.target.value)} maxLength={20} /></label>
      <label><span>{t("work.card.col.plan")}</span>
        <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} aria-invalid={typeof n !== "number"} /></label>
      <label><span>{t("work.card.col.price")}</span>
        <input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} aria-invalid={p === undefined} /></label>
      <div className={cx(css.row, css.wide)}>
        <button type="submit" className={css.primary} disabled={busy || !valid}>{t("work.card.lineAdd")}</button>
        <button type="button" onClick={() => setOpen(false)}>{t("work.form.cancel")}</button>
      </div>
    </form>
  );
}

// Photos and PDF reports: a grid of tiles, each opens the file in a new tab. Upload — several
// files one after another; a file over 15 MB is refused before sending; 413 / 415 of the server
// are said in words. On a phone (coarse pointer) there are two buttons: the camera and the gallery
// (capture alone would leave no way to pick an existing photo)
function Photos({ task, state, run, busy, me, upload, onError }: {
  task: WorkTask; state: WorkState; run: WorkRun; busy: boolean; me: string | null; upload: boolean; onError: () => void;
}) {
  const { t } = useTranslation();
  const [sending, setSending] = useState<string | null>(null);   // the file being uploaded
  const [problems, setProblems] = useState<string[]>([]);
  const phone = typeof window !== "undefined" && !!window.matchMedia?.("(pointer: coarse)").matches;
  useEffect(() => setProblems([]), [task.id]);

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    const out: string[] = [];
    for (const file of Array.from(files)) {
      if (file.size > PHOTO_MAX) { out.push(t("work.card.tooBig", { name: file.name })); continue; }
      setSending(file.name);
      let refused: unknown = null;
      await run(async (key) => {
        try { return await uploadWorkPhoto(key, task.id, file); } catch (e) { refused = e; throw e; }
      });
      if (refused instanceof WorkError && refused.status === 413) out.push(t("work.card.tooBig", { name: file.name }));
      else if (refused instanceof WorkError && refused.status === 415) out.push(t("work.card.badType", { name: file.name }));
      else if (refused) out.push(t("work.card.uploadFailed", { name: file.name, error: (refused as Error).message }));
    }
    setSending(null);
    setProblems(out);
    if (out.length) onError();  // the reasons are under the photos, per file: not twice
  };
  const removePhoto = (id: string, name: string) => {
    if (confirm(t("work.card.deletePhotoAsk", { name }))) void run((key) => deleteWorkPhoto(key, id));
  };
  const picker = (capture: boolean, text: string) => (
    <label className={cx(css.upload, (busy || !!sending) && css.disabled)}>
      <input type="file" accept="image/*,application/pdf" multiple={!capture} capture={capture ? "environment" : undefined}
             disabled={busy || !!sending} onChange={(e) => { void send(e.target.files); e.target.value = ""; }} />
      {text}
    </label>
  );
  return (
    <div className={css.photos}>
      {task.photos.length > 0 ? (
        <ul className={css.grid}>
          {task.photos.map((p) => (
            <li key={p.id} className={css.photo}>
              <a href={p.url} target="_blank" rel="noreferrer" title={p.file_name}>
                {isPicture(p) ? <img src={p.url} alt={p.caption || p.file_name} loading="lazy" />
                  : <span className={css.file}>{isPdf(p) ? "PDF" : (p.file_name.split(".").pop() ?? "").toUpperCase()}</span>}
              </a>
              <span className={css.caption}>
                {p.caption || p.file_name}
                <span className="muted"> · {p.author} · {t("work.card.mb", { size: fileSize(p.size, locale()) })}</span>
              </span>
              {canDeletePhoto(p, task, state.plan, state.can, me) && (
                <button type="button" className={css.unphoto} disabled={busy} aria-label={t("work.card.deletePhoto")}
                        title={t("work.card.deletePhoto")} onClick={() => removePhoto(p.id, p.file_name)}>×</button>
              )}
            </li>
          ))}
        </ul>
      ) : <p className="muted small">{t("work.card.noPhotos")}</p>}
      {upload && (
        <div className={css.row}>
          {phone ? (
            <>
              {picker(true, t("work.card.shoot"))}
              {picker(false, t("work.card.pick"))}
            </>
          ) : picker(false, t("work.card.upload"))}
        </div>
      )}
      {sending && <p className="muted small" role="status">{t("work.card.uploading", { name: sending })}</p>}
      {problems.length > 0 && <ul className={css.problems} role="alert">{problems.map((x) => <li key={x}>{x}</li>)}</ul>}
    </div>
  );
}

// The feed: comments, status changes (a quiet line) and returns (marked, with the reason)
function Feed({ task, run, busy, write }: { task: WorkTask; run: WorkRun; busy: boolean; write: boolean }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const loc = locale();
  const items = feedOf(task.comments);
  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!text.trim()) return;
    if (await run((key) => addWorkComment(key, task.id, text.trim()))) setText("");
  };
  return (
    <div className={css.feed}>
      {items.length ? (
        <ol className={css.items}>
          {items.map((c) => (
            <li key={c.id} className={cx(css.entry, c.kind === "status" && css.change, c.kind === "return" && css.returned)}>
              <span className={css.who}>
                <b>{c.author || t("work.card.someone")}</b>
                {c.kind === "status" && c.status && <> {t("work.card.moved")} <WorkStatusBadge status={c.status} /></>}
                {c.kind === "return" && <> {t("work.card.returned")}</>}
                <time className="muted" dateTime={c.created_at ?? undefined}>{moment(c.created_at, loc)}</time>
              </span>
              {c.on_behalf && <span className={css.behalf}>{behalfText(c.on_behalf, "feed")}</span>}
              {c.text && <p>{c.text}</p>}
            </li>
          ))}
        </ol>
      ) : <p className="muted small">{t("work.card.noFeed")}</p>}
      {write && (
        <form className={css.comment} onSubmit={submit}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={4000}
                    placeholder={t("work.card.comment")} aria-label={t("work.card.comment")} />
          <button type="submit" disabled={busy || !text.trim()}>{t("work.card.send")}</button>
        </form>
      )}
    </div>
  );
}

// Payments: date, sum, note; the studio adds (an advance is a payment before acceptance) and deletes
function Payments({ task, currency, run, busy, add, remove }: { task: WorkTask; currency: string; run: WorkRun; busy: boolean; add: boolean; remove: boolean }) {
  const { t } = useTranslation();
  const loc = locale();
  const left = Math.max(0, task.total - task.paid);
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(today);
  const [note, setNote] = useState("");
  const n = parseAmount(amount);
  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (typeof n !== "number" || n <= 0 || !date) return;
    if (await run((key) => addWorkPayment(key, task.id, { amount: n, paid_on: date, note: note.trim() || undefined }))) {
      setAmount(""); setNote("");
    }
  };
  const unpay = (id: string, sum: number) => {
    if (confirm(t("work.card.unpayAsk", { amount: money(sum, currency, loc) }))) void run((key) => deleteWorkPayment(key, id));
  };
  return (
    <div className={css.payments}>
      {task.payments.length ? (
        <ul className={css.paid}>
          {task.payments.map((p) => (
            <li key={p.id}>
              <span>{day(p.paid_on, loc)}</span>
              <b>{money(p.amount, currency, loc)}</b>
              <span className="muted">{p.note}</span>
              {remove && (
                <button type="button" className={css.unphoto} disabled={busy} aria-label={t("work.card.unpay")}
                        title={t("work.card.unpay")} onClick={() => unpay(p.id, p.amount)}>×</button>
              )}
            </li>
          ))}
        </ul>
      ) : <p className="muted small">{t("work.card.noPayments")}</p>}
      {add && (
        <form className={css.payForm} onSubmit={submit}>
          <label><span>{t("work.card.amount")}</span>
            <input inputMode="decimal" value={amount} placeholder={left > 0 ? String(left) : ""}
                   onChange={(e) => setAmount(e.target.value)} aria-invalid={n === undefined} /></label>
          <label><span>{t("work.card.date")}</span>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
          <label className={css.wide}><span>{t("work.card.note")}</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></label>
          <div className={cx(css.row, css.wide)}>
            <button type="submit" className={css.primary} disabled={busy || typeof n !== "number" || n <= 0}>{t("work.card.pay")}</button>
            {left > 0 && <button type="button" onClick={() => setAmount(String(Math.round(left * 100) / 100))}>{t("work.card.payRest", { amount: money(left, currency, loc) })}</button>}
          </div>
        </form>
      )}
    </div>
  );
}
