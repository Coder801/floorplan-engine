// The "Tasks" tab (docs/work-tasks.md): installation by tasks in place of the drawing. The studio
// and installers (work_manage or work_do) get the board (widgets/WorkBoard), the client and a view
// code — the list in work order (widgets/WorkList). No plan yet: "Create tasks from the estimate"
// for the studio, "The studio is still preparing the plan" for the others. The data and writes are
// the page's (useWork.ts): every write replaces the whole state; the card is in the side panel.

import { useTranslation } from "react-i18next";
import type { WorkState } from "@/shared/types";
import { emptyOf, layoutOf, type WorkRun } from "@/shared/work";
import { Card } from "@/ui/Card";
import { ErrorState } from "@/ui/ErrorState";
import { Heading } from "@/ui/Heading";
import { MarkLoader } from "@/ui/MarkLoader";
import { Text } from "@/ui/Text";
import { WorkBoard } from "@/widgets/WorkBoard";
import { WorkList } from "@/widgets/WorkList";
import { WorkPlanActions } from "@/widgets/WorkPlanActions";
import css from "./WorkStage.module.scss";

interface Props {
  state: WorkState | null;
  error: string | null;
  busy: boolean;
  run: WorkRun;
  open: string | null;
  onOpen: (task: string) => void;
}

export function WorkStage({ state, error, busy, run, open, onOpen }: Props) {
  const { t } = useTranslation();
  if (!state) {
    return error ? <ErrorState>{error}</ErrorState> : (
      <div className={css.loading} role="status"><MarkLoader /><Text as="span" size="small" tone="muted">{t("work.loading")}</Text></div>
    );
  }
  const empty = emptyOf(state);
  // A refusal without an open card (plan buttons, the add form) is said over the board
  const shownError = error && !open ? <div className={css.error} role="alert">{error}</div> : null;
  if (empty) {
    return (
      <div className={css.empty}>
        <Card padding="md" className={css.emptyCard}>
          <Heading level={1}>{t("work.title")}</Heading>
          <Text tone="muted">{t(`work.empty.${empty}`)}</Text>
          {empty === "create" && <WorkPlanActions state={state} run={run} busy={busy} />}
          {shownError}
        </Card>
      </div>
    );
  }
  const layout = layoutOf(state.can);
  return (
    <>
      {layout === "board"
        ? <WorkBoard state={state} run={run} busy={busy} open={open} onOpen={onOpen} />
        : <WorkList state={state} run={run} busy={busy} open={open} onOpen={onOpen} />}
      {shownError && <div className={css.toast}>{shownError}</div>}
    </>
  );
}
