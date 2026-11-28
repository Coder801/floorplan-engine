// An opened question thread (docs/question-threads.md, "Просмотр"): at the top a follow-up thread
// links to the previous one and quotes the answer accepted there; then what the questions panel
// adds (the form of a value, choice or groups question, "show on the drawing"); the state; the
// message feed, oldest first — an AI check message with its reason and what it changed in the
// model; the reply field — a choice asked of the client or the installer offers its options as
// buttons that fill it. The studio (review) accepts a person's message as the answer — the thread
// goes to checking, the card shows it and polls until the check ends (useThread) — or closes the
// thread, with an optional comment. A thread that is not open only reads (decision 2026-11-28).

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import i18n, { anyKey, locale } from "@/shared/i18n";
import { acceptable, acceptedIn, rightsOf } from "@/shared/threadList";
import { threadsApi, type Thread, type ThreadMessage, type ThreadsApi } from "@/shared/threads";
import type { Project } from "@/shared/types";
import { Button } from "@/ui/Button";
import { Text } from "@/ui/Text";
import { TextArea } from "@/ui/TextArea";
import css from "./ThreadCard.module.scss";
import { useThread } from "./useThread";

const MAX = 2000;  // characters of a message

interface Props {
  projectKey: string;
  summary: Thread;              // the row of the list: shown until the thread itself is read
  can: Project["can"];
  extra?: ReactNode;            // from the questions panel: the answer form, "show on the drawing"
  draft: string;
  onDraft: (text: string) => void;
  onChanged: () => void;        // written or checked: the list reads its rows again
  onOpen: (id: string) => void; // the previous thread of the chain
  api?: ThreadsApi;
}

const when = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(locale(), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

export function ThreadCard({ projectKey, summary, can, extra, draft, onDraft, onChanged, onOpen, api = threadsApi }: Props) {
  const { t } = useTranslation();
  const th = useThread(api, projectKey, summary.id, onChanged);
  const [closing, setClosing] = useState(false);
  const [comment, setComment] = useState("");
  const d = th.detail;
  const state = d?.state ?? summary.state;
  const rights = rightsOf(d ?? summary, can);
  const previous = d?.previous[0];
  const quoted = acceptedIn(previous);
  const accepted = d?.accepted_message_id ?? summary.accepted_message_id;
  const q = d?.question ?? summary.question;
  // A clarifying choice: the options fill the reply, it is still sent as a message
  const options = q && q.kind === "choice" && q.audience !== "studio" ? q.options : [];
  const studio = can?.review === true;

  const send = async () => {
    const text = draft.trim();
    if (!text) return;
    if (await th.run(() => api.send(projectKey, summary.id, text))) onDraft("");
  };
  const close = async () => {
    if (await th.run(() => api.close(projectKey, summary.id, comment.trim() || undefined))) { setClosing(false); setComment(""); }
  };

  return (
    <div className={css.card}>
      {previous && (
        <div className={css.chain}>
          <Button variant="link" className={css.quiet} onClick={() => onOpen(previous.id)}>{`← ${t("threads.previous")}`}</Button>
          {quoted && (
            <blockquote className={css.quote}>
              <Text as="span" size="caps" tone="muted">{t("threads.quote")}</Text>
              <span>{`«${quoted.text}»`}</span>
            </blockquote>
          )}
        </div>
      )}
      {extra}
      <StateBand state={state} />
      <Text as="h4" size="caps" tone="muted">{t("threads.feed")}</Text>
      {!d && !th.error && <Text size="small" tone="muted">{t("threads.loadingThread")}</Text>}
      {d && (d.messages.length === 0
        ? <Text size="small" tone="muted">{t("threads.noMessages")}</Text>
        : (
          <ol className={css.feed}>
            {d.messages.map((m) => (
              <Message key={m.id} m={m} accepted={m.accepted || m.id === accepted}
                       onAccept={rights.accept && acceptable(m) && !th.busy
                         ? () => void th.run(() => api.accept(projectKey, summary.id, m.id)) : undefined} />
            ))}
          </ol>
        ))}
      {rights.write && d && (
        <form className={css.reply} onSubmit={(ev) => { ev.preventDefault(); void send(); }}>
          {options.length > 0 && (
            <div className={css.options} role="group" aria-label={t("threads.options")}>
              {options.map((v) => (
                <Button key={v} size="sm" onClick={() => onDraft(q?.option_labels[v] ?? v)}>{q?.option_labels[v] ?? v}</Button>
              ))}
            </div>
          )}
          <TextArea label={t("threads.message")} value={draft} maxLength={MAX} rows={3}
                    hint={t(studio ? "threads.replyHintStudio" : "threads.replyHint")}
                    onChange={(ev) => onDraft(ev.target.value)} />
          <div className={css.actions}>
            <Button type="submit" variant="primary" disabled={th.busy || !draft.trim()}>{t("threads.send")}</Button>
          </div>
        </form>
      )}
      {rights.close && d && (closing ? (
        <form className={css.reply} onSubmit={(ev) => { ev.preventDefault(); void close(); }}>
          <TextArea label={t("threads.closeComment")} value={comment} maxLength={MAX} rows={2} hint={t("threads.closeHint")}
                    onChange={(ev) => setComment(ev.target.value)} />
          <div className={css.actions}>
            <Button type="submit" variant="danger" disabled={th.busy}>{t("threads.closeYes")}</Button>
            <Button variant="link" className={css.quiet} onClick={() => setClosing(false)}>{t("threads.cancel")}</Button>
          </div>
        </form>
      ) : (
        <div className={css.actions}>
          <Button variant="link" className={css.quiet} disabled={th.busy} onClick={() => setClosing(true)}>{t("threads.close")}</Button>
        </div>
      ))}
      {th.error && <Text size="small" tone="critical" role="alert" className={css.failure}>{th.error}</Text>}
    </div>
  );
}

// What happens with the thread: the check in progress, or how it ended
function StateBand({ state }: { state: Thread["state"] }) {
  const { t } = useTranslation();
  if (state === "open") return null;
  if (state === "checking") {
    return (
      <div className={css.band} role="status">
        <span className={css.ring} />
        <span>
          <b>{t("threads.checking")}</b>
          <Text as="span" size="small" tone="muted" className={css.block}>{t("threads.checkingHint")}</Text>
        </span>
      </div>
    );
  }
  return <div className={cx(css.band, css[state])} role="status"><span>{t(`threads.${state}`)}</span></div>;
}

function Message({ m, accepted, onAccept }: { m: ThreadMessage; accepted: boolean; onAccept?: () => void }) {
  const { t } = useTranslation();
  const tr = anyKey(t);
  // An unknown role reads as it came
  const role = m.role && (i18n.exists(`threads.roles.${m.role}`) ? tr(`threads.roles.${m.role}`) : m.role);
  const who = m.author === "user" ? [m.author_label, role, m.mine && t("threads.you")].filter(Boolean).join(" · ") : t(`threads.author.${m.author}`);
  const meta = m.author === "analyzer" ? m.meta : null;
  return (
    <li className={cx(css.message, m.author !== "user" && css.machine, accepted && css.accepted)}>
      <div className={css.who}>
        <span>{who}</span>
        <span className="muted">{when(m.created_at)}</span>
      </div>
      {m.text && <div className={css.text}>{m.text}</div>}
      {meta?.verdict && <div className={cx(css.verdict, css[meta.verdict])}>{t(`threads.verdict.${meta.verdict}`)}</div>}
      {meta?.reason && <div className={css.text}>{meta.reason}</div>}
      {meta?.changes && meta.changes.length > 0 && (
        <div>
          <Text as="span" size="caps" tone="muted">{t("threads.changes")}</Text>
          <ul className={css.changes}>{meta.changes.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
      )}
      {accepted && <div className={css.acceptedMark}>{`✓ ${t("threads.accepted")}`}</div>}
      {onAccept && !accepted && (
        <div className={css.actions}>
          <Button size="sm" onClick={onAccept}>{t("threads.accept")}</Button>
        </div>
      )}
    </li>
  );
}
