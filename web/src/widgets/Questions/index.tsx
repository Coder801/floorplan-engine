// Project questions in the slide-out panel: short rows with one open card, an answer right in the
// card. A value, a choice and a kept assumption rebuild the project (the panel stays usable, the
// next question opens at once); a text answer is only saved and waits for the analyzer. Who may
// answer — can.answer; the studio also sees ids and field paths. A client question only clarifies
// (decision 2026-11-11): any answer goes as { text }, the studio takes it into account or sends it
// back with a comment (can.review).

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AnswerRefused, type AnswerResult, type ReviewOutcome } from "@/shared/api";
import { cx } from "@/shared/cx";
import i18n, { label } from "@/shared/i18n";
import {
  forClient, groupOf, keepOrder, listOrder, nextOpen, parseNumber, plainNumber, returnedComment, shortMessage, shownOn, statusOf,
  type Answer, type Group, type QuestionsMemory, type Status,
} from "@/shared/questions";
import type { Project, Question } from "@/shared/types";
import { Button } from "@/ui/Button";
import { IconButton } from "@/ui/IconButton";
import { Text } from "@/ui/Text";
import css from "./Questions.module.scss";

interface Props {
  project: Project;
  busy: boolean;  // an answer is being saved or the project reloaded
  // null: the person chose to stay with unsaved route edits
  onAnswer: (id: string, answer: Answer | null) => Promise<AnswerResult | null>;
  onReview: (id: string, outcome: ReviewOutcome, comment?: string) => Promise<AnswerResult | null>;
  stages: string[];  // stages of the sheets: where "show" can lead
  onShow: (to: { stage: string; key: string | null }) => void;
  memory: React.MutableRefObject<QuestionsMemory>;  // the panel closes, this stays
}

type Failure = AnswerRefused | string;

interface CardProps {
  q: Question;
  answer: unknown;
  status: Status;
  can: boolean;       // this person may answer
  studio: boolean;    // ids, field paths, whole check messages
  reviewer: boolean;  // takes client answers into account or sends them back
  busy: boolean;
  working: boolean;   // this question's answer is being checked and the project rebuilt
  editing: boolean;
  asking: boolean;    // "remove the answer?" is shown
  draft?: string;     // undefined: nothing typed yet (editing starts from the current answer)
  failure?: Failure;
  onDraft: (text: string) => void;
  onSave: (answer: Answer | null) => void;
  onEdit: (on: boolean) => void;
  onAsk: (on: boolean) => void;
  onOpen: (id: string) => void;
  onLocal: (message: string) => void;
  onReview: (outcome: ReviewOutcome, comment?: string) => void;
}

export function Questions({ project: p, busy, onAnswer, onReview, stages, onShow, memory }: Props) {
  const { t } = useTranslation();
  const qs = p.report?.questions ?? [];
  const can = p.can?.answer === true;
  const studio = p.can?.edit_wiring !== false;
  const reviewer = p.can?.review === true;
  const order = useRef<Map<string, Group>>(listOrder(qs, p.answers));
  order.current = keepOrder(order.current, qs);
  const ids = [...order.current.keys()];
  const byId = new Map(qs.map((q) => [q.id, q]));
  const status = (id: string): Status => statusOf(p.answers[id]);
  const firstOpen = ids.find((id) => groupOf(status(id)) === "open");
  const [expanded, setExpanded] = useState<string | null>(
    memory.current.expanded !== undefined ? memory.current.expanded : can ? firstOpen ?? null : null);
  const [drafts, setDrafts] = useState<Record<string, string>>(memory.current.drafts);
  const [closedShown, setClosedShown] = useState(memory.current.closedShown === true);  // closed ones fold away
  memory.current = { drafts, expanded, closedShown };
  const [failures, setFailures] = useState<Record<string, Failure>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);  // the question that rebuilds the project
  const [done, setDone] = useState<number | null>(null);  // the rebuild ended: how the list changed
  const wasBusy = useRef(false);
  const settled = useRef(false);  // the server has rebuilt: the end of busy is the end of the build
  const before = useRef(qs.length);

  useEffect(() => {
    if (busy) { wasBusy.current = true; return; }
    if (!wasBusy.current) return;
    wasBusy.current = false;
    if (settled.current) {
      settled.current = false;
      setWorking(null);
      setDone(qs.length - before.current);
    }
  }, [busy, qs.length]);

  if (!p.report) return <Text tone="muted">{t("drawer.noReport")}</Text>;
  if (!qs.length) return <Text tone="muted">{t("drawer.noQuestions")}</Text>;

  const fail = (id: string, failure: Failure | null) => setFailures((all) => {
    const { [id]: _, ...rest } = all;
    return failure === null ? rest : { ...rest, [id]: failure };
  });

  const save = async (q: Question, answer: Answer | null) => {
    const isText = typeof answer === "object" && answer !== null && "text" in answer;
    const rebuilds = !isText && !(answer === null && status(q.id) === "pending");
    const next = () => nextOpen(ids, (id) => (id === q.id ? "answered" : status(id)), q.id);
    fail(q.id, null);
    setAsking(null);
    setDone(null);
    setWorking(rebuilds ? q.id : null);
    before.current = qs.length;
    // The build takes a while, and the next question can be read and filled meanwhile
    if (answer !== null && rebuilds) setExpanded(next());
    try {
      const result = await onAnswer(q.id, answer);
      if (result === null) {
        setExpanded(q.id);
        setWorking(null);
        return;
      }
      setEditing(null);
      setDrafts(({ [q.id]: _, ...rest }) => rest);
      if (result.rebuilt) settled.current = true;
      else if (isText) setExpanded(next());
    } catch (e) {
      fail(q.id, e instanceof AnswerRefused ? e : (e as Error).message);
      setExpanded(q.id);
      setWorking(null);
    }
  };

  // Taken into account: the question closes and the project is rebuilt; sent back: only saved
  const review = async (q: Question, outcome: ReviewOutcome, comment?: string) => {
    fail(q.id, null);
    setDone(null);
    setWorking(outcome === "resolve" ? q.id : null);
    before.current = qs.length;
    try {
      const result = await onReview(q.id, outcome, comment);
      if (result === null) { setWorking(null); return; }
      setDrafts(({ [q.id]: _, ...rest }) => rest);
      if (result.rebuilt) settled.current = true;
      else setWorking(null);
    } catch (e) {
      fail(q.id, e instanceof AnswerRefused ? e : (e as Error).message);
      setWorking(null);
    }
  };

  const counts = ids.reduce((n, id) => ({ ...n, [groupOf(status(id))]: n[groupOf(status(id))] + 1 }),
                            { open: 0, pending: 0, closed: 0 } as Record<Group, number>);

  const card = (q: Question) => (
    <Card key={q.id} q={q} answer={p.answers[q.id]} status={status(q.id)} can={can} studio={studio} reviewer={reviewer}
          busy={busy} working={working === q.id} editing={editing === q.id} asking={asking === q.id}
          draft={drafts[q.id]} failure={failures[q.id]}
          open={expanded === q.id}
          shows={shownOn(q, stages)} onShow={onShow}
          onToggle={() => setExpanded(expanded === q.id ? null : q.id)}
          onDraft={(text) => setDrafts((all) => ({ ...all, [q.id]: text }))}
          onSave={(answer) => void save(q, answer)}
          onEdit={(on) => {
            setEditing(on ? q.id : null);
            fail(q.id, null);
            setDrafts(({ [q.id]: _, ...rest }) => rest);
          }}
          onAsk={(on) => setAsking(on ? q.id : null)}
          onOpen={setExpanded}
          onLocal={(message) => fail(q.id, message)}
          onReview={(outcome, comment) => void review(q, outcome, comment)} />
  );

  const group = (g: Group, title: string) => {
    const rows = ids.filter((id) => order.current.get(id) === g).flatMap((id) => byId.get(id) ?? []);
    if (!rows.length) return false;
    if (g !== "closed") return <><div className={css.group}>{title}</div>{rows.map(card)}</>;
    // Closed questions are folded: they open on a click, or when one of them is opened from a link
    const shown = closedShown || rows.some((q) => q.id === expanded);
    return (
      <>
        <button type="button" className={cx(css.group, css.fold)} aria-expanded={shown} onClick={() => setClosedShown(!shown)}>
          <span>{`${title} · ${rows.length}`}</span>
          <span className={css.chevron} aria-hidden="true">{shown ? "▴" : "▾"}</span>
        </button>
        {shown && rows.map(card)}
      </>
    );
  };

  return (
    <>
      <div className={css.strip}>
        {/* The right edge stays free: "Review answers", one per project, comes with step Б6 */}
        <div className={css.counts}>
          <span><b>{counts.open}</b> {t("questions.needN")}</span>
          <span><b>{counts.pending}</b> {t("questions.pendN")}</span>
          <span><b>{counts.closed}</b> {t("questions.doneN")}</span>
        </div>
        {!can && <div className={css.readOnly}>{t("questions.readOnly")}</div>}
        {working !== null && (
          <div className={css.band} role="status"><span className={css.ring} />{t("questions.rebuilding")}</div>
        )}
        {done !== null && !busy && (
          <div className={cx(css.band, css.ok)} role="status">
            <span>
              <b>{t("questions.rebuilt")}</b>
              {done < 0 && ` ${t("questions.fewer", { n: -done })}`}
              {done > 0 && ` ${t("questions.more", { n: done })}`}
            </span>
            <IconButton variant="close" label={t("common.close")} onClick={() => setDone(null)} />
          </div>
        )}
      </div>
      {group("open", t("questions.groupOpen"))}
      {group("pending", t("questions.groupPending"))}
      {group("closed", t("questions.groupClosed"))}
    </>
  );
}

// Card stripe by severity (critical, major, minor); an unknown one has none
const SEVERITY: Record<string, string | undefined> = { critical: css.critical, major: css.major, minor: css.minor };

interface RowProps extends CardProps {
  open: boolean;
  onToggle: () => void;
  shows: { stage: string; key: string | null } | null;  // where "show" leads
  onShow: (to: { stage: string; key: string | null }) => void;
}

function Card(props: RowProps) {
  const { q, answer, status, can, studio, reviewer, working, failure, open, onToggle, shows, onShow } = props;
  const { t } = useTranslation();
  const word = working ? "rebuilding" : status === "open" ? null : status;
  const comment = returnedComment(answer);
  return (
    <div className={cx(css.row, SEVERITY[q.severity], groupOf(status) === "closed" && css.done,
                       open && css.expanded, failure && css.failed)}>
      <button type="button" className={css.head} aria-expanded={open} onClick={onToggle}>
        <span className={css.meta}>
          <span className={`sev-${q.severity}`}>
            {`${label("severity", q.severity)} · ${label("stage", q.stage)}`}
            {studio && forClient(q) && ` · ${t("questions.forClient")}`}
            {studio && <span className={cx(css.id, "mono muted")}>{` · ${q.id}`}</span>}
          </span>
          {word && <span className={cx(css.word, css[word])}>{t(`questions.status.${word}`)}</span>}
        </span>
        <span className={css.chevron} aria-hidden="true">{open ? "▴" : "▾"}</span>
        <span className={cx(css.text, !open && css.clamp)}>{q.text}</span>
        {!open && <Summary q={q} answer={answer} status={status} />}
      </button>
      {open && (
        <div>
          {q.assumption !== undefined && q.answer !== "choice" && status === "open" && (
            <div className={css.now}>{t("questions.now", { value: shown(q, q.assumption) })}</div>
          )}
          {comment && status === "returned" && <div className={css.returned}>{t("questions.returnedBy", { comment })}</div>}
          {can ? <Controls {...props} /> : <Answered q={q} answer={answer} status={status} empty />}
          {forClient(q) && status === "pending" && (reviewer ? <Review {...props} /> : can && <div className={css.hint}>{t("questions.clientWaits")}</div>)}
          {forClient(q) && status === "resolved" && <div className={css.hint}>{t("questions.resolvedClient")}</div>}
          {shows && (
            <div className={css.actions}>
              <Button variant="link" className={css.quiet} onClick={() => onShow(shows)}>
                {t(q.answer === "groups" ? "questions.pickGroups" : shows.key ? "questions.show" : "questions.showPanel")}
              </Button>
            </div>
          )}
          {studio && q.target && <div className={css.path}>{q.target}</div>}
          {studio && q.also && q.also.length > 0 && <div className={css.hint}>{t("questions.also", { n: q.also.length })}</div>}
        </div>
      )}
    </div>
  );
}

// An option or a value as a person reads it
function shown(q: Question, value: unknown): string {
  if (q.option_labels && typeof value === "string" && q.option_labels[value]) return q.option_labels[value];
  const unit = q.unit === "mm" ? i18n.t("units.mm") : q.unit;
  return `${plainNumber(value)}${unit && typeof value !== "string" ? ` ${unit}` : ""}`;
}

function answerValue(q: Question, answer: unknown): string {
  if (Array.isArray(answer)) return answer.join(", ");
  const o = answer as { text?: string };
  if (!o || typeof o !== "object") return shown(q, answer);
  // A client value or choice is kept as text: it reads as the value it is
  if (forClient(q) && q.answer === "value") return shown(q, parseNumber(o.text ?? "") ?? o.text);
  if (forClient(q) && q.answer === "choice") return shown(q, o.text);
  return `«${o.text}»`;
}

function kept(q: Question): string {
  return q.assumption !== undefined ? i18n.t("questions.kept", { value: shown(q, q.assumption) }) : i18n.t("questions.keptPlain");
}

function Summary({ q, answer, status }: { q: Question; answer: unknown; status: Status }) {
  const { t } = useTranslation();
  if (status === "open") {
    return q.assumption !== undefined
      ? <span className={cx(css.summary, "muted")}>{t("questions.now", { value: shown(q, q.assumption) })}</span> : null;
  }
  return <span className={cx(css.summary, css.clamp)}>{status === "accepted" ? kept(q) : answerValue(q, answer)}</span>;
}

function Answered({ q, answer, status, empty }: { q: Question; answer: unknown; status: Status; empty?: boolean }) {
  const { t } = useTranslation();
  if (status === "open") return empty ? <div className={cx(css.answer, "muted")}>{t("questions.noAnswer")}</div> : null;
  if (status === "accepted") return <div className={css.answer}>{kept(q)}</div>;
  return <div className={css.answer}>{t("questions.answer", { value: answerValue(q, answer) })}</div>;
}

function Controls(props: CardProps) {
  const { q, answer, status, working, editing, asking, onEdit, onAsk, onSave } = props;
  if (q.answer === "groups") return <Answered q={q} answer={answer} status={status} />;
  const { t } = useTranslation();
  if (working) {
    return (
      <>
        <Answered q={q} answer={answer} status={status} />
        <div className={css.busy} role="status"><span className={css.ring} />{t("questions.checking")}</div>
        <div className={css.hint}>{t("questions.wait")}</div>
      </>
    );
  }
  if (status === "open" || status === "returned" || editing) return <Form {...props} />;
  const resolved = status === "resolved";
  return (
    <>
      <Answered q={q} answer={answer} status={status} />
      {asking ? (
        <>
          <div className={css.hint}>{t("questions.removeAsk")}</div>
          <div className={css.actions}>
            <Button onClick={() => onSave(null)}>{t("questions.removeYes")}</Button>
            <Button variant="link" className={css.quiet} onClick={() => onAsk(false)}>{t("questions.removeNo")}</Button>
          </div>
        </>
      ) : (
        <div className={css.actions}>
          <Button variant="link" className={css.quiet} onClick={() => onEdit(true)}>{t("questions.edit")}</Button>
          {!resolved && (
            <Button variant="link" className={css.quiet} onClick={() => (status === "pending" ? onAsk(true) : onSave(null))}>
              {t("questions.remove")}
            </Button>
          )}
        </div>
      )}
      {resolved && !forClient(q) && <div className={css.hint}>{t("questions.resolvedNote")}</div>}
      <FailureBox {...props} />
    </>
  );
}

function Form(props: CardProps) {
  const { q, answer, busy, editing, draft, failure, onDraft, onSave, onEdit, onLocal } = props;
  const { t } = useTranslation();
  const unit = q.unit === "mm" ? i18n.t("units.mm") : q.unit;
  const keep = q.assumption !== undefined && q.answer !== "choice" && !editing ? (
    <Button block className={css.keep} disabled={busy} onClick={() => onSave({ accept: true })}>
      {q.answer === "value" ? t("questions.keep", { value: shown(q, q.assumption) }) : t("questions.keepPlain")}
    </Button>
  ) : null;
  const client = forClient(q);
  const before = typeof answer === "object" && answer !== null ? (answer as { text?: string }).text : answer;
  const value = draft ?? (editing && before !== undefined ? plainNumber(before) : "");
  let form: React.ReactNode;
  if (q.answer === "choice") {
    const chosen = editing ? before : undefined;
    form = (
      <div className={css.options} role="radiogroup" aria-label={t("questions.yourAnswer")}>
        {(q.options ?? []).map((v) => (
          <button key={v} type="button" className={css.option} role="radio" aria-checked={v === chosen} disabled={busy}
                  onClick={() => onSave(client ? { text: v } : v === q.assumption ? { accept: true } : v)}>
            <span className={css.dot} />
            <span>
              {shown(q, v)}
              {props.studio && q.option_labels?.[v] && <span className={cx(css.raw, "mono")}>{v}</span>}
            </span>
            {v === q.assumption && <span className={css.tag}>{t("questions.nowTag")}</span>}
          </button>
        ))}
      </div>
    );
  } else if (q.answer === "value") {
    form = (
      <form onSubmit={(ev) => {
        ev.preventDefault();
        const n = parseNumber(value);
        if (n === null) onLocal(t("questions.notNumber"));
        else onSave(client ? { text: plainNumber(n) } : n);
      }}>
        <label className={css.label} htmlFor={`q-${q.id}`}>{t("questions.yourAnswer")}</label>
        <div className={css.valueRow}>
          <div className={cx(css.field, failure && css.bad)}>
            <input id={`q-${q.id}`} inputMode="decimal" autoComplete="off" value={value}
                   aria-invalid={!!failure} onChange={(ev) => onDraft(ev.target.value)} />
            {unit && <span className={css.unit}>{unit}</span>}
          </div>
          <Button type="submit" variant="primary" size="lg" disabled={busy}>{t("questions.save")}</Button>
        </div>
      </form>
    );
  } else {
    const text = draft ?? (editing ? (answer as { text?: string })?.text ?? "" : "");
    form = (
      <form onSubmit={(ev) => {
        ev.preventDefault();
        if (text.trim()) onSave({ text: text.trim() });
      }}>
        <label className={css.label} htmlFor={`q-${q.id}`}>{t("questions.yourAnswer")}</label>
        <textarea id={`q-${q.id}`} className={cx(css.area, failure && css.bad)} value={text} maxLength={2000}
                  aria-invalid={!!failure} onChange={(ev) => onDraft(ev.target.value)} />
        <div className={css.hint}>{t(q.severity === "critical" ? "questions.textCritical" : "questions.textHint")}</div>
        <div className={css.actions}>
          <Button type="submit" variant="primary" disabled={busy || !text.trim()}>{t("questions.send")}</Button>
        </div>
      </form>
    );
  }
  return (
    <>
      {form}
      <FailureBox {...props} />
      {keep}
      {busy && <div className={css.hint}>{t("questions.locked")}</div>}
      {editing && (
        <div className={css.actions}>
          <Button variant="link" className={css.quiet} onClick={() => onEdit(false)}>{t("questions.cancel")}</Button>
        </div>
      )}
    </>
  );
}

// The studio on a client answer waiting for it: taken into account, or sent back with a comment
function Review(props: CardProps) {
  const { busy, working, draft, onDraft, onReview } = props;
  const { t } = useTranslation();
  const [back, setBack] = useState(false);
  if (working) return null;
  if (!back) {
    return (
      <>
        <div className={css.actions}>
          <Button variant="primary" disabled={busy} onClick={() => onReview("resolve")}>{t("questions.accept")}</Button>
          <Button variant="link" className={css.quiet} disabled={busy} onClick={() => setBack(true)}>{t("questions.sendBack")}</Button>
        </div>
        <div className={css.hint}>{t("questions.reviewHint")}</div>
        {!props.can && <FailureBox {...props} />}
      </>
    );
  }
  const text = draft ?? "";
  return (
    <form onSubmit={(ev) => {
      ev.preventDefault();
      if (text.trim()) onReview("return", text.trim());
    }}>
      <label className={css.label} htmlFor={`back-${props.q.id}`}>{t("questions.backComment")}</label>
      <textarea id={`back-${props.q.id}`} className={css.area} value={text} maxLength={2000}
                onChange={(ev) => onDraft(ev.target.value)} />
      <div className={css.actions}>
        <Button type="submit" variant="primary" disabled={busy || !text.trim()}>{t("questions.backSend")}</Button>
        <Button variant="link" className={css.quiet} onClick={() => setBack(false)}>{t("questions.cancel")}</Button>
      </div>
      {!props.can && <FailureBox {...props} />}
    </form>
  );
}

function FailureBox({ q, studio, failure, onOpen }: CardProps) {
  const { t } = useTranslation();
  if (!failure) return null;
  if (typeof failure === "string") return <div className={css.failure} role="alert">{failure}</div>;
  return (
    <div className={css.failure} role="alert">
      <b>{t("questions.notSaved")}</b>
      {failure.issues.map((i, k) => (
        <div key={k}>
          <div className={css.message}>{studio ? i.message : shortMessage(i.message)}</div>
          {studio && i.path !== q.target && <div className={cx(css.path, "mono")}>{`${i.file}: ${i.path}`}</div>}
        </div>
      ))}
      {failure.blockedBy.map((b) => (
        <div key={b.id} className={css.message}>
          {t("questions.blockedBy")}{" "}
          <Button variant="link" className={css.quiet} onClick={() => onOpen(b.id)}>{b.text}</Button>
        </div>
      ))}
    </div>
  );
}
