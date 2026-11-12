// Side panel of the "Tasks" tab: the plan in numbers — state, who approved and when, model
// version, work / materials / total / paid, accepted tasks, lines without a price

import { useTranslation } from "react-i18next";
import { locale } from "@/shared/i18n";
import type { WorkState } from "@/shared/types";
import { behalfText, day, modelChanged, money } from "@/shared/work";
import css from "./WorkSummary.module.scss";

export function WorkSummary({ state }: { state: WorkState | null }) {
  const { t } = useTranslation();
  const plan = state?.plan;
  if (!state || !plan || (plan.state === "draft" && !state.can.work_manage && !state.can.work_do)) {
    return <p className="muted">{t("work.summary.none")}</p>;
  }
  const loc = locale();
  const m = (v: number) => money(v, plan.currency, loc);
  const tt = plan.totals;
  return (
    <div className={css.summary}>
      <dl className={css.pairs}>
        <dt>{t("work.summary.state")}</dt><dd>{t(`work.plan.${plan.state}`)}</dd>
        {plan.approved_at && (
          <>
            <dt>{t("work.summary.approved")}</dt>
            <dd>
              {day(plan.approved_at, loc)}{plan.approved_by ? ` · ${plan.approved_by}` : ""}
              {plan.approved_on_behalf && <span className={css.behalf}>{behalfText(plan.approved_on_behalf, "plan")}</span>}
            </dd>
          </>
        )}
        {plan.closed_at && <><dt>{t("work.summary.closed")}</dt><dd>{day(plan.closed_at, loc)}</dd></>}
        {plan.model_version !== null && <><dt>{t("work.summary.version")}</dt><dd>{plan.model_version}</dd></>}
        <dt>{t("work.accepted")}</dt><dd>{t("work.ofN", { n: tt.accepted, m: tt.tasks })}</dd>
      </dl>
      {modelChanged(state) && <p className={css.note}>{t("work.modelChanged", { plan: plan.model_version, now: state.model_version })}</p>}
      <dl className={css.totals}>
        <dt>{t("work.card.work")}</dt><dd>{m(tt.work)}</dd>
        <dt>{t("work.card.materials")}</dt><dd>{m(tt.material)}</dd>
        <dt className={css.grand}>{t("work.card.total")}</dt><dd className={css.grand}>{m(tt.total)}</dd>
        <dt>{t("work.card.paid")}</dt><dd>{m(tt.paid)}</dd>
        <dt>{t("work.summary.left")}</dt><dd>{m(Math.max(0, tt.total - tt.paid))}</dd>
      </dl>
      {tt.unpriced > 0 && <p className={css.note}>{t("work.card.unpricedNote", { n: tt.unpriced })}</p>}
      <p className="muted small">{t("work.summary.lead")}</p>
    </div>
  );
}
