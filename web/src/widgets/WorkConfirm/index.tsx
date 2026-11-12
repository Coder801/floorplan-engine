// "How did the client confirm?" (decision 2026-11-12): the studio approves the plan, agrees to
// extra work, accepts or returns a task only for the client and says how the client confirmed it —
// by phone, in Telegram or otherwise, with an optional note. Asked before sending; the client side
// never sees it (shared/work.ts, needsBehalf). A modal over the whole screen, in a portal: the task
// card under it is a panel with its own stacking. Esc and a click on the veil cancel.

import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { WorkChannel, WorkOnBehalf } from "@/shared/types";
import { CHANNELS, NOTE_MAX } from "@/shared/work";
import { Button } from "@/ui/Button";
import { Heading } from "@/ui/Heading";
import { Modal } from "@/ui/Modal";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Stack } from "@/ui/Stack";
import { Text } from "@/ui/Text";
import { TextArea } from "@/ui/TextArea";
import css from "./WorkConfirm.module.scss";

interface Props {
  action: string;          // what is done for the client, in words: "Принять"
  detail?: string;         // more about it: the plan sum
  busy: boolean;
  onConfirm: (onBehalf: WorkOnBehalf) => void;
  onCancel: () => void;
}

export function WorkConfirm({ action, detail, busy, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const [channel, setChannel] = useState<WorkChannel | null>(null);
  const [note, setNote] = useState("");
  const channels = useRef<HTMLDivElement>(null);
  const title = useId();
  const lead = useId();

  useEffect(() => { channels.current?.querySelector("button")?.focus(); }, []);

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (channel) onConfirm({ channel, note: note.trim() });
  };
  return (
    <Modal as="form" size="sm" onClose={onCancel} onSubmit={submit} labelledBy={title} describedBy={lead}>
      <Heading level={2} id={title}>{t("work.behalf.title")}</Heading>
      <Text id={lead} tone="muted" className={css.lead}>
        {t("work.behalf.lead", { action })}
        {detail && <><br /><b>{detail}</b></>}
      </Text>
      <div ref={channels}>
        <SegmentedControl fill size="lg" label={t("work.behalf.title")} value={channel} onChange={setChannel}
                          options={CHANNELS.map((c) => ({ value: c, label: t(`work.behalf.channel.${c}`) }))} />
      </div>
      <TextArea label={t("work.behalf.note")} value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={NOTE_MAX}
                placeholder={t("work.behalf.notePlaceholder")} />
      <Stack direction="row" gap={2} className={css.buttons}>
        <Button type="submit" variant="primary" disabled={busy || !channel}>{t("work.behalf.ok")}</Button>
        <Button onClick={onCancel}>{t("work.form.cancel")}</Button>
      </Stack>
    </Modal>
  );
}
