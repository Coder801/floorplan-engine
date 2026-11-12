// "Leave feedback" (decision 2026-11-12): a message about the service itself — a bug, an idea or
// other — to the platform owner (the admin app, "Отзывы"); not about a work task. A modal over
// everything, in a portal: kind, text with a counter, up to three screenshots (picked or pasted),
// a hint about what is attached by itself (feedback.ts, contextOf), then a short thanks. Esc
// closes; a click on the veil closes only an empty form, so a typed message is not lost by a miss.
// Tab stays inside the card; the focus returns where it was.

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FeedbackError, sendFeedback } from "@/shared/api";
import type { FeedbackBody, FeedbackKind } from "@/shared/types";
import { APP_VERSION, BUILD_ID } from "@/shared/version";
import { Button } from "@/ui/Button";
import { Heading } from "@/ui/Heading";
import { IconButton } from "@/ui/IconButton";
import { Modal } from "@/ui/Modal";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Stack } from "@/ui/Stack";
import { Text } from "@/ui/Text";
import { TextArea } from "@/ui/TextArea";
import {
  addPhotos, browserWhere, contextOf, failureOf, FEEDBACK_KINDS, PHOTO_TYPES, PHOTOS_MAX, TEXT_MAX, textOk, type Where,
} from "./feedback";
import css from "./Feedback.module.scss";

interface Props {
  project?: { key: string; title: string } | null;  // the open project, if any
  sheet?: string | null;        // the context sheet id (feedback.ts, sheetOf)
  sheetTitle?: string | null;   // the same in words, for the hint
  onClose: () => void;
  send?: (body: FeedbackBody) => Promise<{ id: string }>;  // Storybook: without the API
  where?: () => Where;
}

export function Feedback({ project = null, sheet = null, sheetTitle = null, onClose, send = sendFeedback, where = browserWhere }: Props) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<FeedbackKind>("bug");
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [refused, setRefused] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const title = useId();
  const lead = useId();
  const version = `${APP_VERSION} (${BUILD_ID})`;

  // Previews of the attached screenshots; the object URLs are freed with them
  const previews = useMemo(() => photos.map((f) => URL.createObjectURL(f)), [photos]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  // Focus: the text on open, "Close" after the thanks (Modal traps Tab and gives the focus back)
  useEffect(() => { area.current?.focus(); }, []);
  useEffect(() => { if (done) closeBtn.current?.focus(); }, [done]);

  const add = (files: File[]) => {
    if (!files.length) return;
    const got = addPhotos(photos, files);
    setPhotos(got.photos);
    setRefused(got.refused.map((r) => t(`feedback.refused.${r.reason}`, { name: r.name, n: PHOTOS_MAX })));
  };
  const remove = (i: number) => { setPhotos(photos.filter((_, j) => j !== i)); setRefused([]); };

  // A screenshot from the clipboard (Ctrl+V / ⌘V anywhere in the card)
  const onPaste = (ev: React.ClipboardEvent) => {
    const files = [...ev.clipboardData.files].filter((f) => f.type.startsWith("image/"));
    if (!files.length) return;
    ev.preventDefault();
    add(files);
  };

  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (busy || !textOk(text)) return;
    setBusy(true);
    setError(null);
    try {
      await send({ kind, text: text.trim(), context: contextOf(sheet, version, where()), project: project?.key ?? null, photos });
      setDone(true);
    } catch (e) {
      const status = e instanceof FeedbackError ? e.status : null;
      const why = failureOf(status);
      const message = e instanceof Error ? e.message : String(e);
      // 429: the server says in words when to try again — its text, else ours
      setError(why === "rate" && message ? message : t(`feedback.errors.${why}`, { message }));
    } finally {
      setBusy(false);
    }
  };

  const empty = !text.trim() && !photos.length;
  const count = text.trim().length;
  return (
    <Modal as="form" onClose={onClose} closeOnVeil={empty || done} labelledBy={title} describedBy={lead}
           onSubmit={submit} onPaste={done ? undefined : onPaste}>
        {done ? (
          <>
            <Heading level={2} id={title}>{t("feedback.thanks")}</Heading>
            <Text id={lead} tone="muted">{t("feedback.thanksNote")}</Text>
            <Stack direction="row" gap={2} className={css.buttons}>
              <Button ref={closeBtn} variant="primary" onClick={onClose}>{t("feedback.close")}</Button>
            </Stack>
          </>
        ) : (
          <>
            <Heading level={2} id={title}>{t("feedback.title")}</Heading>
            <Text id={lead} tone="muted">{t("feedback.lead")}</Text>
            <SegmentedControl fill label={t("feedback.kind")} value={kind} onChange={setKind} className={css.kinds}
                              options={FEEDBACK_KINDS.map((k) => ({ value: k, label: t(`feedback.kinds.${k}`) }))} />
            <TextArea ref={area} label={t("feedback.text")} value={text} rows={5} maxLength={TEXT_MAX + 200}
                      placeholder={t(`feedback.placeholder.${kind}`)} onChange={(e) => setText(e.target.value)}
                      counter={t("feedback.counter", { n: count, max: TEXT_MAX })} over={count > TEXT_MAX} />
            <div className={css.field}>
              <span className={css.label}>{t("feedback.photos")}<span className={css.counter}>{t("feedback.photosNote", { n: PHOTOS_MAX })}</span></span>
              <div className={css.photos}>
                {photos.map((f, i) => (
                  <div key={previews[i]} className={css.photo}>
                    <img src={previews[i]} alt={f.name} />
                    <IconButton variant="round" size="sm" className={css.remove} label={t("feedback.removePhoto", { name: f.name })}
                                onClick={() => remove(i)}>×</IconButton>
                  </div>
                ))}
                {photos.length < PHOTOS_MAX && (
                  <button type="button" className={css.add} onClick={() => picker.current?.click()}>
                    <span aria-hidden="true">+</span>
                    <span>{t("feedback.addPhoto")}</span>
                  </button>
                )}
              </div>
              <input ref={picker} type="file" hidden accept={PHOTO_TYPES.join(",")} multiple
                     onChange={(e) => { add([...(e.target.files ?? [])]); e.target.value = ""; }} />
              {refused.map((r) => <span key={r} className={css.refused}>{r}</span>)}
            </div>
            <Text size="small" tone="muted">
              {project
                ? t("feedback.attached", { project: project.title, sheet: sheetTitle ?? sheet ?? "—", version })
                : t("feedback.attachedNoProject", { version })}
            </Text>
            {error && <Text tone="critical" role="alert">{error}</Text>}
            <Stack direction="row" gap={2} className={css.buttons}>
              <Button type="submit" variant="primary" disabled={busy || !textOk(text)}>
                {busy ? t("feedback.sending") : t("feedback.send")}
              </Button>
              <Button onClick={onClose}>{t("feedback.cancel")}</Button>
            </Stack>
          </>
        )}
    </Modal>
  );
}
