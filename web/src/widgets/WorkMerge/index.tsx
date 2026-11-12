// "Merge with…" in the task card (work_manage, while the money of both tasks is open): pick the
// task to merge into, confirm, POST /merge {into}. Lines, the feed, the acceptance criterion with
// its ticks and the description move there and this task is deleted, so the card then opens the
// target (onMerged). A task with photos or payments is not merged: the button is disabled and says
// why (shared/work.ts, mergeBlock); other refusals (409 / 422) come from the server into the card.

import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { mergeWorkTask } from "@/shared/api";
import type { WorkState, WorkTask } from "@/shared/types";
import { mergeBlock, mergeTargets, numberOf, type WorkRun } from "@/shared/work";
import { Button } from "@/ui/Button";
import { Select } from "@/ui/Select";
import { Stack } from "@/ui/Stack";
import { Text } from "@/ui/Text";
import css from "./WorkMerge.module.scss";

interface Props {
  task: WorkTask;
  state: WorkState;
  run: WorkRun;
  busy: boolean;
  onMerged: (into: string) => void;
}

export function WorkMerge({ task, state, run, busy, onMerged }: Props) {
  const { t } = useTranslation();
  const targets = mergeTargets(task, state);
  const block = mergeBlock(task, targets);
  const [open, setOpen] = useState(false);
  const [into, setInto] = useState("");
  const hint = useId();
  useEffect(() => { setOpen(false); }, [task.id]);

  const target = targets.find((x) => x.id === into) ?? targets[0];
  const start = () => { setInto(targets[0]?.id ?? ""); setOpen(true); };
  const merge = async () => {
    if (!target || !confirm(t("work.card.mergeAsk", { from: task.title, into: target.title }))) return;
    if (await run((key) => mergeWorkTask(key, task.id, target.id))) onMerged(target.id);
  };

  if (!open) {
    return (
      <div className={css.merge}>
        <Button disabled={busy || !!block} aria-describedby={block ? hint : undefined} onClick={start}>
          {t("work.card.merge")}
        </Button>
        {block && <Text id={hint} size="small" tone="muted">{t(`work.card.mergeBlocked.${block}`)}</Text>}
      </div>
    );
  }
  return (
    <div className={css.form}>
      <Text as="span" size="small" tone="muted">{t("work.card.mergeInto")}</Text>
      <Select label={t("work.card.mergeInto")} value={target?.id ?? ""} onChange={setInto}
              options={targets.map((x) => ({ value: x.id, label: `${numberOf(x, state.tasks)}. ${x.title}` }))} />
      <Stack direction="row" gap={2}>
        <Button variant="primary" disabled={busy || !target} onClick={() => void merge()}>{t("work.card.mergeGo")}</Button>
        <Button onClick={() => setOpen(false)}>{t("work.form.cancel")}</Button>
      </Stack>
    </div>
  );
}
