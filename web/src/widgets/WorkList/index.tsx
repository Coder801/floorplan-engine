// The client's view of the "Tasks" tab (work_accept without work_do and work_manage; a view code
// too): a list in work order made for a phone — number, title, a big status, the sum and what is
// needed from them ("Approve the plan", "Accept the work", "Agree to the extra work"). A row
// opens the task card. A plan the studio has not sent yet is not shown (WorkStage: empty).

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { locale } from "@/shared/i18n";
import type { WorkState } from "@/shared/types";
import { behalfText, money, ordered, planNeed, progressOf, taskNeed, type WorkRun } from "@/shared/work";
import { WorkPlanActions } from "@/widgets/WorkPlanActions";
import { WorkStatusBadge } from "@/widgets/WorkStatusBadge";
import css from "./WorkList.module.scss";

interface Props {
  state: WorkState;
  run: WorkRun;
  busy: boolean;
  open: string | null;
  onOpen: (task: string) => void;
}

export function WorkList({ state, run, busy, open, onOpen }: Props) {
  const { t } = useTranslation();
  const plan = state.plan!;
  const m = (v: number) => money(v, plan.currency, locale());
  const need = planNeed(state);
  const tasks = ordered(state.tasks);
  const p = progressOf(plan.totals);
  const asks = tasks.filter((task) => taskNeed(task, plan, state.can)).length;
  return (
    <div className={css.list}>
      <header className={css.head}>
        <h1>{t("work.title")}</h1>
        <dl className={css.sums}>
          <dt>{t("work.card.total")}</dt><dd>{m(plan.totals.total)}</dd>
          {(plan.state === "approved" || plan.state === "closed") && (
            <>
              <dt>{t("work.card.paid")}</dt><dd>{m(plan.totals.paid)}</dd>
              <dt>{t("work.accepted")}</dt><dd>{t("work.ofN", { n: p.accepted, m: p.tasks })}</dd>
            </>
          )}
        </dl>
        {plan.state === "closed" && <p className={css.lead}>{t("work.plan.closed")}</p>}
        {plan.approved_on_behalf && <p className={css.behalf}>{behalfText(plan.approved_on_behalf, "plan")}</p>}
        {need && (
          <div className={css.ask}>
            <b>{t(`work.need.${need}`)}</b>
            <p>{t("work.approveLead")}</p>
            <WorkPlanActions state={state} run={run} busy={busy} only={["approve"]} big />
          </div>
        )}
        {asks > 0 && <p className={css.waitingYou}>{t("work.asksN", { n: asks })}</p>}
      </header>
      <ol className={css.items}>
        {tasks.map((task, i) => {
          const ask = taskNeed(task, plan, state.can);
          return (
            <li key={task.id}>
              <button type="button" className={cx(css.item, ask && css.asked, task.id === open && css.open)}
                      aria-pressed={task.id === open} onClick={() => onOpen(task.id)}>
                <span className={css.num}>{i + 1}</span>
                <span className={css.body}>
                  <b className={css.name}>{task.title}{task.extra && <span className={css.extra}> · {t("work.extra")}</span>}</b>
                  <span className={css.row}>
                    {plan.state === "approved" || plan.state === "closed" ? <WorkStatusBadge status={task.status} big /> : <span />}
                    <span className={css.sum}>{m(task.total)}</span>
                  </span>
                  {ask && <span className={css.need}>{t(`work.need.${ask}`)} →</span>}
                  {!ask && task.settled && task.total > 0 && <span className={css.paid}>{t("work.paidMark")}</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
