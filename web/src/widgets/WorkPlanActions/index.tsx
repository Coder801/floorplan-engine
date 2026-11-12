// Plan buttons of the "Tasks" tab by the plan state and the rights (shared/work.ts, planActions):
// create from the estimate, send to the client, approve, discard, close; "Add task" opens the
// form of the board (onAdd). Discarding and approving ask first; the studio approves only for the
// client and is asked how the client confirmed (widgets/WorkConfirm).

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { createWorkPlan, workPlanAction } from "@/shared/api";
import { cx } from "@/shared/cx";
import { locale } from "@/shared/i18n";
import type { WorkState } from "@/shared/types";
import { money, needsBehalf, planActions, type PlanAction, type WorkRun } from "@/shared/work";
import { WorkConfirm } from "@/widgets/WorkConfirm";
import css from "./WorkPlanActions.module.scss";

interface Props {
  state: WorkState;
  run: WorkRun;
  busy: boolean;
  onAdd?: () => void;     // the board's "Add task" form; without it, no button
  only?: PlanAction[];    // show only these (the client list: approve)
  big?: boolean;          // one large button (the client on a phone)
}

const PRIMARY = new Set<PlanAction>(["create", "propose", "approve", "close"]);

export function WorkPlanActions({ state, run, busy, onAdd, only, big }: Props) {
  const { t } = useTranslation();
  const [asking, setAsking] = useState(false);   // the studio approves: the client's channel first
  const actions = planActions(state).filter((a) => (!only || only.includes(a)) && (a !== "add" || onAdd));
  if (!actions.length) return null;
  const plan = state.plan;
  const total = plan ? money(plan.totals.total, plan.currency, locale()) : "";
  const press = (a: PlanAction) => {
    if (a === "add") { onAdd?.(); return; }
    if (a === "create") { void run(createWorkPlan); return; }
    if (a === "approve" && needsBehalf(a, state.can)) { setAsking(true); return; }
    if (a === "discard" && !confirm(t("work.discardAsk"))) return;
    if (a === "approve" && plan && !confirm(t("work.approveAsk", { total }))) return;
    void run((key) => workPlanAction(key, a));
  };
  const name = (a: PlanAction) => (a === "discard" && plan?.state === "proposed" ? t("work.actions.recall") : t(`work.actions.${a}`));
  return (
    <div className={cx(css.actions, big && css.big)}>
      {actions.map((a) => (
        <button key={a} type="button" className={cx(PRIMARY.has(a) && css.primary)} disabled={busy} onClick={() => press(a)}>
          {name(a)}
        </button>
      ))}
      {asking && (
        <WorkConfirm action={t("work.actions.approve")} detail={t("work.approveAsk", { total })} busy={busy}
                     onCancel={() => setAsking(false)}
                     onConfirm={(ob) => void run((key) => workPlanAction(key, "approve", ob)).then(() => setAsking(false))} />
      )}
    </div>
  );
}
