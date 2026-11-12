// "Leave feedback" (decision 2026-11-12): a message about the service itself — a bug, an idea or
// other — to the platform owner (the admin app, "Отзывы"); not about a work task. A modal over
// everything, in a portal: kind, text with a counter, up to three screenshots (picked or pasted),
// a hint about what is attached by itself (feedback.ts, contextOf), then a short thanks. Esc
// closes; a click on the veil closes only an empty form, so a typed message is not lost by a miss.
// Tab stays inside the card; the focus returns where it was.

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { FeedbackError, sendFeedback } from "@/shared/api";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { FeedbackBody, FeedbackKind } from "@/shared/types";
import { APP_VERSION, BUILD_ID } from "@/shared/version";
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

const FOCUSABLE = "button:not(:disabled), textarea, input:not([type=file]), [href]";

export function Feedback({ project = null, sheet = null, sheetTitle = null, onClose, send = sendFeedback, where = browserWhere }: Props) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<FeedbackKind>("bug");
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [refused, setRefused] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const card = useRef<HTMLFormElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const title = useId();
  const lead = useId();
  const version = `${APP_VERSION} (${BUILD_ID})`;

  // Previews of the attached screenshots; the object URLs are freed with them
  const previews = useMemo(() => photos.map((f) => URL.createObjectURL(f)), [photos]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

  // Focus: the text on open, "Close" after the thanks; back to where it was on close
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    area.current?.focus();
    return () => before?.focus?.();
  }, []);
  useEffect(() => { if (done) closeBtn.current?.focus(); }, [done]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") { ev.stopPropagation(); onClose(); return; }
      if (ev.key !== "Tab" || !card.current) return;
      const all = [...card.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (!all.length) return;
      const first = all[0], last = all[all.length - 1];
      const inside = card.current.contains(document.activeElement);
      if (ev.shiftKey && (document.activeElement === first || !inside)) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && (document.activeElement === last || !inside)) { ev.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

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
  return createPortal(
    <div className={css.veil} data-veil="" onClick={() => { if (empty || done) onClose(); }}>
      <form ref={card} className={css.card} data-pop="modal" role="dialog" aria-modal="true" aria-labelledby={title} aria-describedby={lead}
            onClick={(ev) => ev.stopPropagation()} onSubmit={submit} onPaste={done ? undefined : onPaste}>
        {done ? (
          <>
            <h2 id={title} className={css.title}>{t("feedback.thanks")}</h2>
            <p id={lead} className={css.lead}>{t("feedback.thanksNote")}</p>
            <div className={css.buttons}>
              <button ref={closeBtn} type="button" className={css.primary} onClick={onClose}>{t("feedback.close")}</button>
            </div>
          </>
        ) : (
          <>
            <h2 id={title} className={css.title}>{t("feedback.title")}</h2>
            <p id={lead} className={css.lead}>{t("feedback.lead")}</p>
            <div className={cx(ui.segmented, css.kinds)} role="radiogroup" aria-label={t("feedback.kind")}>
              {FEEDBACK_KINDS.map((k) => (
                <button key={k} type="button" role="radio" aria-checked={kind === k} className={cx(kind === k && ui.on)}
                        onClick={() => setKind(k)}>{t(`feedback.kinds.${k}`)}</button>
              ))}
            </div>
            <label className={css.field}>
              <span className={css.label}>
                {t("feedback.text")}
                <span className={cx(css.counter, count > TEXT_MAX && css.over)} aria-live="polite">
                  {t("feedback.counter", { n: count, max: TEXT_MAX })}
                </span>
              </span>
              <textarea ref={area} value={text} rows={5} maxLength={TEXT_MAX + 200} placeholder={t(`feedback.placeholder.${kind}`)}
                        onChange={(e) => setText(e.target.value)} />
            </label>
            <div className={css.field}>
              <span className={css.label}>{t("feedback.photos")}<span className={css.counter}>{t("feedback.photosNote", { n: PHOTOS_MAX })}</span></span>
              <div className={css.photos}>
                {photos.map((f, i) => (
                  <div key={previews[i]} className={css.photo}>
                    <img src={previews[i]} alt={f.name} />
                    <button type="button" className={css.remove} aria-label={t("feedback.removePhoto", { name: f.name })}
                            title={t("feedback.removePhoto", { name: f.name })} onClick={() => remove(i)}>×</button>
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
            <p className={css.attached}>
              {project
                ? t("feedback.attached", { project: project.title, sheet: sheetTitle ?? sheet ?? "—", version })
                : t("feedback.attachedNoProject", { version })}
            </p>
            {error && <p className={css.error} role="alert">{error}</p>}
            <div className={css.buttons}>
              <button type="submit" className={css.primary} disabled={busy || !textOk(text)}>
                {busy ? t("feedback.sending") : t("feedback.send")}
              </button>
              <button type="button" onClick={onClose}>{t("feedback.cancel")}</button>
            </div>
          </>
        )}
      </form>
    </div>,
    document.body,
  );
}
