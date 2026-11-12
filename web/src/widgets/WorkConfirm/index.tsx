// "How did the client confirm?" (decision 2026-11-12): the studio approves the plan, agrees to
// extra work, accepts or returns a task only for the client and says how the client confirmed it —
// by phone, in Telegram or otherwise, with an optional note. Asked before sending; the client side
// never sees it (shared/work.ts, needsBehalf). A modal over the whole screen, in a portal: the task
// card under it is a panel with its own stacking. Esc and a click on the veil cancel.

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { WorkChannel, WorkOnBehalf } from "@/shared/types";
import { CHANNELS, NOTE_MAX } from "@/shared/work";
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
  const first = useRef<HTMLButtonElement>(null);
  const title = useId();
  const lead = useId();

  useEffect(() => {
    first.current?.focus();
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") { ev.stopPropagation(); onCancel(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onCancel]);

  const submit = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (channel) onConfirm({ channel, note: note.trim() });
  };
  return createPortal(
    <div className={css.veil} data-veil="" onClick={onCancel}>
      <form className={css.card} data-pop="modal" role="dialog" aria-modal="true" aria-labelledby={title} aria-describedby={lead}
            onClick={(ev) => ev.stopPropagation()} onSubmit={submit}>
        <h2 id={title} className={css.title}>{t("work.behalf.title")}</h2>
        <p id={lead} className={css.lead}>
          {t("work.behalf.lead", { action })}
          {detail && <><br /><b>{detail}</b></>}
        </p>
        <div className={cx(ui.segmented, css.channels)} role="radiogroup" aria-label={t("work.behalf.title")}>
          {CHANNELS.map((c, i) => (
            <button key={c} ref={i === 0 ? first : undefined} type="button" role="radio" aria-checked={channel === c}
                    className={cx(channel === c && ui.on)} onClick={() => setChannel(c)}>
              {t(`work.behalf.channel.${c}`)}
            </button>
          ))}
        </div>
        <label className={css.note}>
          <span>{t("work.behalf.note")}</span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={NOTE_MAX}
                    placeholder={t("work.behalf.notePlaceholder")} />
        </label>
        <div className={css.buttons}>
          <button type="submit" className={css.primary} disabled={busy || !channel}>{t("work.behalf.ok")}</button>
          <button type="button" onClick={onCancel}>{t("work.form.cancel")}</button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
