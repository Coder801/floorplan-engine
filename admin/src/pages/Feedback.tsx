// Product feedback from the viewer ("Оставить отзыв", decision 2026-11-12), full width: a status
// filter with counts, a kind filter and a search over the text and the author; each message with
// the date, kind, author, project, text, what the page attached and the screenshots (a click opens
// one full size). The status moves in one click (new → seen → done, or any by the segmented), the
// note is saved by a button. A change stays in place even if it leaves the filter.
import { useEffect, useState } from "react";
import * as api from "@/shared/api";
import { agentOf, applyChange, authorOf, contextOf, FEEDBACK_KINDS, FEEDBACK_STATUSES, nextStatus } from "@/shared/feedback";
import { date } from "@/shared/format";
import { href } from "@/shared/route";
import { FEEDBACK_KIND, FEEDBACK_STATUS, word } from "@/shared/text";
import type { FeedbackItem, FeedbackStatus } from "@/shared/types";
import { Dialog, ErrorLine, Segmented, Status, css, cx, useAction, useLoad } from "@/components/ui";

const LIMIT = 50;

export function Feedback({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<string>("new");
  const [kind, setKind] = useState("");
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [photo, setPhoto] = useState<string | null>(null);
  useEffect(() => { const t = setTimeout(() => setQ(typed.trim()), 250); return () => clearTimeout(t); }, [typed]);
  useEffect(() => setOffset(0), [status, kind, q]);
  const list = useLoad(() => api.feedback({ status, kind, q, offset, limit: LIMIT }), [status, kind, q, offset]);
  const page = list.data;
  const all = page ? FEEDBACK_STATUSES.reduce((n, s) => n + (page.counts[s] ?? 0), 0) : 0;
  const changed = (item: FeedbackItem) => {
    if (page) list.set(applyChange(page, item));
    onChanged();  // the count of new ones in the sections
  };
  return (
    <>
      <h1 className={css.title}>Отзывы</h1>
      <div className={css.meta}>
        <Segmented options={["", ...FEEDBACK_STATUSES]} value={status} onChange={setStatus}
                   label={(s) => `${s ? word(FEEDBACK_STATUS, s) : "все"}${page ? ` ${s ? page.counts[s as FeedbackStatus] ?? 0 : all}` : ""}`} />
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Все виды</option>
          {FEEDBACK_KINDS.map((k) => <option key={k} value={k}>{word(FEEDBACK_KIND, k)}</option>)}
        </select>
        <input placeholder="Текст или автор" value={typed} onChange={(e) => setTyped(e.target.value)} />
      </div>
      <ErrorLine error={list.error} />
      {page && !page.items.length && <div className={css.empty}>Отзывов нет</div>}
      <div className={css.feedList}>
        {page?.items.map((item) => <FeedbackCard key={item.id} item={item} onChanged={changed} onPhoto={setPhoto} />)}
      </div>
      {page && page.total > LIMIT && (
        <div className={css.pager}>
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>← Новее</button>
          <span className={css.muted}>{offset + 1}–{Math.min(offset + LIMIT, page.total)} из {page.total}</span>
          <button disabled={offset + LIMIT >= page.total} onClick={() => setOffset(offset + LIMIT)}>Старше →</button>
        </div>
      )}
      {photo && (
        <Dialog title="Скриншот" onClose={() => setPhoto(null)}>
          <a href={photo} target="_blank" rel="noreferrer"><img className={css.full} src={photo} alt="Скриншот" /></a>
        </Dialog>
      )}
    </>
  );
}

function FeedbackCard({ item, onChanged, onPhoto }: {
  item: FeedbackItem; onChanged: (item: FeedbackItem) => void; onPhoto: (url: string) => void;
}) {
  const action = useAction();
  const [note, setNote] = useState(item.admin_note ?? "");
  const next = nextStatus(item.status);
  const save = (change: { status?: FeedbackStatus; admin_note?: string }) =>
    void action.run(() => api.updateFeedback(item.id, change), onChanged);
  const context = contextOf(item.context);
  return (
    <article className={cx(css.feedItem, item.status === "new" && css.fresh)}>
      <div className={css.feedHead}>
        <span className={css.mono}>{date(item.created_at)}</span>
        <span className={cx(css.kind, css[item.kind])}>{word(FEEDBACK_KIND, item.kind)}</span>
        <span>{authorOf(item.author)}{item.author?.email && item.author.name ? <span className={css.muted}> · {item.author.email}</span> : null}</span>
        {item.project && <a className={css.link} href={href("projects", item.project.key)}>{item.project.name}</a>}
        <span className={css.feedStatus}><Status state={item.status} label={word(FEEDBACK_STATUS, item.status)} /></span>
      </div>
      <p className={css.feedText}>{item.text}</p>
      {item.photos.length > 0 && (
        <div className={css.thumbs}>
          {item.photos.map((url, i) => (
            <button key={url} className={css.thumb} onClick={() => onPhoto(url)} aria-label={`Скриншот ${i + 1}`}>
              <img src={url} alt="" loading="lazy" />
            </button>
          ))}
        </div>
      )}
      {context.length > 0 && <div className={css.rowSub} title={agentOf(item.context)}>{context.join(" · ")}</div>}
      <div className={css.feedActions}>
        <Segmented options={FEEDBACK_STATUSES} value={item.status} label={(s) => word(FEEDBACK_STATUS, s)}
                   onChange={(s) => { if (s !== item.status) save({ status: s as FeedbackStatus }); }} />
        {next && <button className={css.primary} disabled={action.busy} onClick={() => save({ status: next })}>→ {word(FEEDBACK_STATUS, next)}</button>}
        <input className={css.note} placeholder="Заметка для себя" value={note} onChange={(e) => setNote(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && note !== (item.admin_note ?? "")) save({ admin_note: note }); }} />
        {note !== (item.admin_note ?? "") && <button disabled={action.busy} onClick={() => save({ admin_note: note })}>Сохранить</button>}
      </div>
      <ErrorLine error={action.error} />
    </article>
  );
}
