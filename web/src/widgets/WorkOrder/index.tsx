// Where a task stands in the plan, in the task card: its number in work order with "Up" / "Down"
// (buttons, so it works on a phone too) and the tasks it goes after ("after": the installer takes it
// once those are accepted). The studio (work_manage, plan not closed) changes both: PATCH position —
// the neighbour's place (shared/work.ts, shiftTo), PATCH after — ids of the ticked tasks. The server
// refuses a cycle (422 "after: зависимость по кругу…"): the card shows its text.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { editWorkTask } from "@/shared/api";
import type { WorkState, WorkTask } from "@/shared/types";
import { afterOf, numberOf, ordered, shiftTo, type WorkRun } from "@/shared/work";
import css from "./WorkOrder.module.scss";

interface Props {
  task: WorkTask;
  state: WorkState;
  run: WorkRun;
  busy: boolean;
  editable: boolean;
}

export function WorkOrder({ task, state, run, busy, editable }: Props) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const after = afterOf(task, state.tasks);
  const afterKey = after.map((a) => a.id).join(",");
  useEffect(() => { setEditing(false); }, [task.id, afterKey]);

  const n = numberOf(task, state.tasks);
  const up = shiftTo(state.tasks, task.id, -1);
  const down = shiftTo(state.tasks, task.id, 1);
  const move = (position: number | null) => {
    if (position !== null) void run((key) => editWorkTask(key, task.id, { position }));
  };
  const others = ordered(state.tasks).filter((x) => x.id !== task.id);
  const start = () => { setPicked(new Set(after.map((a) => a.id))); setEditing(true); };
  const toggle = (id: string) => setPicked((prev) => {
    const next = new Set(prev);
    if (!next.delete(id)) next.add(id);
    return next;
  });
  const save = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const ids = others.filter((x) => picked.has(x.id)).map((x) => x.id);
    if (await run((key) => editWorkTask(key, task.id, { after: ids }))) setEditing(false);
  };
  const label = (x: WorkTask) => `${numberOf(x, state.tasks)}. ${x.title}`;

  if (!editable && !after.length) return null;
  return (
    <div className={css.order}>
      {editable && (
        <div className={css.place}>
          <span className={css.label}>{t("work.card.order")}</span>
          <span className={css.number}>{t("work.card.orderN", { n, m: state.tasks.length })}</span>
          <span className={css.arrows}>
            <button type="button" disabled={busy || up === null} onClick={() => move(up)}
                    aria-label={t("work.card.up")} title={t("work.card.up")}>↑</button>
            <button type="button" disabled={busy || down === null} onClick={() => move(down)}
                    aria-label={t("work.card.down")} title={t("work.card.down")}>↓</button>
          </span>
        </div>
      )}
      {!editing && (
        <div className={css.after}>
          <span className={css.label}>{t("work.card.after")}</span>
          <span>
            {after.length ? after.map(label).join(", ") : <span className="muted">{t("work.card.afterNone")}</span>}
            {editable && others.length > 0 && (
              <> <button type="button" className={css.link} onClick={start}>{t("work.card.afterEdit")}</button></>
            )}
          </span>
        </div>
      )}
      {editing && (
        <form className={css.form} onSubmit={save}>
          <fieldset>
            <legend>{t("work.card.after")}</legend>
            <p className="muted small">{t("work.card.afterLead")}</p>
            <ul className={css.choices}>
              {others.map((x) => (
                <li key={x.id}>
                  <label>
                    <input type="checkbox" checked={picked.has(x.id)} onChange={() => toggle(x.id)} />
                    <span>{label(x)}</span>
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
          <div className={css.buttons}>
            <button type="submit" className={css.primary} disabled={busy}>{t("work.card.afterSave")}</button>
            <button type="button" onClick={() => setEditing(false)}>{t("work.form.cancel")}</button>
          </div>
        </form>
      )}
    </div>
  );
}
