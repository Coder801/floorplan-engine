// Questions as threads (the database viewer, docs/question-threads.md, "Просмотр"): the studio
// sees tabs by audience — client, installer, studio — with the live count and a dot where
// something waits for it; the client and the installer see only their own list (the server
// filters it). Above — how many wait for this person (waiting_for_you of the server). A row:
// severity, stage, the chain ("3-й тред по вопросу"), the state and "waiting for you" or whose
// turn it is (waiting_for); one row opens at a time into its card
// (widgets/ThreadCard). Finished threads fold away as in the folder viewer. While a thread is
// checked and its card is closed, the list asks again every POLL_MS; a thread that left checking
// (resolved — a new model version and a build) makes the page read the project again (onSettled).
// GET /threads answering 404 — no threads on this server: onUnavailable, the panel goes back to
// answers.yaml.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { label } from "@/shared/i18n";
import type { QuestionsMemory } from "@/shared/questions";
import { audienceOf, firstTab, isLive, lastWords, POLL_MS, tabCounts, threadOrder } from "@/shared/threadList";
import { ThreadError, threadsApi, type Thread, type ThreadList, type ThreadsApi } from "@/shared/threads";
import type { Audience, Project } from "@/shared/types";
import { Button } from "@/ui/Button";
import { Tabs } from "@/ui/Tabs";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";
import { ThreadCard } from "@/widgets/ThreadCard";
import css from "./Threads.module.scss";

interface Props {
  project: Project;
  extraFor: (qid: string) => ReactNode;                // the form and links of the questions panel
  notice?: ReactNode;                                  // the rebuild band of a form answer
  drafts: Record<string, string>;                      // replies under "thread:<id>"
  onDraft: (key: string, text: string) => void;
  memory: React.MutableRefObject<QuestionsMemory>;     // the open thread and tab outlive the panel
  onUnavailable: () => void;
  onSettled: () => void;
  api?: ThreadsApi;
}

const SEVERITY: Record<string, string | undefined> = { critical: css.critical, major: css.major, minor: css.minor };
const draftKey = (id: string) => `thread:${id}`;

export function Threads({ project: p, extraFor, notice, drafts, onDraft, memory, onUnavailable, onSettled, api = threadsApi }: Props) {
  const { t } = useTranslation();
  const studio = p.can?.review === true;
  const [found, setFound] = useState<ThreadList | null>(null);
  const threads = found?.threads ?? null;
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Audience | null>((memory.current.tab as Audience | undefined) ?? null);
  const [openId, setOpenId] = useState<string | null>(memory.current.thread ?? null);
  const [closedShown, setClosedShown] = useState(false);
  memory.current.thread = openId;
  if (tab) memory.current.tab = tab;
  const checking = useRef<Set<string>>(new Set());  // what was checking at the last read
  const hooks = useRef({ onUnavailable, onSettled });
  hooks.current = { onUnavailable, onSettled };

  const load = useCallback(async () => {
    try {
      const list = await api.list(p.id);
      const now = new Set(list.threads.filter((x) => x.state === "checking").map((x) => x.id));
      const ended = [...checking.current].some((id) => !now.has(id));
      checking.current = now;
      setFound(list);
      setError(null);
      if (ended) hooks.current.onSettled();
    } catch (e) {
      if (e instanceof ThreadError && e.status === 404) hooks.current.onUnavailable();
      else setError((e as Error).message);
    }
  }, [api, p.id]);

  // Read again when the project is read again (an answer by a form, a rebuild)
  useEffect(() => { void load(); }, [load, p]);

  // A thread is checked with its card closed: only the list tells when it ends
  const unseen = threads?.some((x) => x.state === "checking" && x.id !== openId) ?? false;
  useEffect(() => {
    if (!unseen) return;
    const timer = setTimeout(() => void load(), POLL_MS);
    return () => clearTimeout(timer);
  }, [unseen, threads, load]);

  if (error && !threads) {
    return (
      <div className={css.failed} role="alert">
        <Text tone="critical">{t("threads.failed", { message: error })}</Text>
        <Button onClick={() => void load()}>{t("threads.retry")}</Button>
      </div>
    );
  }
  if (!found || !threads) return <Text tone="muted">{t("threads.loading")}</Text>;

  const counts = tabCounts(threads);
  const shownTab = tab ?? firstTab(counts);
  const shown = threadOrder(studio ? threads.filter((x) => audienceOf(x) === shownTab) : threads);
  const waiting = found.waiting_for_you;
  const live = shown.filter((x) => isLive(x.state));
  const done = shown.filter((x) => !isLive(x.state));

  const open = (id: string) => {
    const found = threads.find((x) => x.id === id);
    if (found && studio) setTab(audienceOf(found));
    setOpenId(id);
  };

  const row = (x: Thread) => {
    return (
      <Row key={x.id} thread={x} studio={studio} open={openId === x.id} onToggle={() => setOpenId(openId === x.id ? null : x.id)}>
        <ThreadCard projectKey={p.id} summary={x} can={p.can} extra={x.question ? extraFor(x.question.id) : null} api={api}
                    draft={drafts[draftKey(x.id)] ?? ""} onDraft={(text) => onDraft(draftKey(x.id), text)}
                    onChanged={() => void load()} onOpen={open} />
      </Row>
    );
  };

  const list = (
    <>
      {!shown.length && <Text tone="muted" className={css.empty}>{t(threads.length ? "threads.emptyTab" : "threads.empty")}</Text>}
      {live.length > 0 && <><div className={css.group}>{t("threads.groupLive")}</div>{live.map(row)}</>}
      {done.length > 0 && (() => {
        const unfolded = closedShown || done.some((x) => x.id === openId);
        return (
          <>
            <button type="button" className={cx(css.group, css.fold)} aria-expanded={unfolded} onClick={() => setClosedShown(!unfolded)}>
              <span>{`${t("threads.groupClosed")} · ${done.length}`}</span>
              <span className={css.chevron} aria-hidden="true">{unfolded ? "▴" : "▾"}</span>
            </button>
            {unfolded && done.map(row)}
          </>
        );
      })()}
    </>
  );

  return (
    <>
      <div className={css.strip}>
        <div className={css.counts}>
          {waiting
            ? <span><b>{waiting}</b> {t(studio ? "threads.waitingDecision" : "threads.waitingMine")}</span>
            : <span>{t("threads.waitingNone")}</span>}
        </div>
        {!p.can?.answer && !studio && <div className={css.readOnly}>{t("threads.readOnly")}</div>}
        {notice}
        {error && <Text size="small" tone="critical" role="alert">{error}</Text>}
      </div>
      {studio ? (
        <Tabs label={t("threads.tabs")} value={shownTab} onChange={setTab}
              tabs={counts.map((c) => ({
                value: c.audience, label: t(`threads.audience.${c.audience}`), count: c.live || undefined, mark: c.waiting > 0,
                ariaLabel: c.waiting ? t("threads.tabWaiting", { name: t(`threads.audience.${c.audience}`), n: c.waiting }) : undefined,
              }))}>
          {list}
        </Tabs>
      ) : list}
    </>
  );
}

function Row({ thread: x, studio, open, onToggle, children }: { thread: Thread; studio: boolean; open: boolean; onToggle: () => void; children: ReactNode }) {
  const { t } = useTranslation();
  const q = x.question;
  const mine = x.waiting_for_you;
  const turn = x.waiting_for;
  const last = lastWords(x);
  return (
    <div className={cx(css.row, SEVERITY[q?.severity ?? ""], !isLive(x.state) && css.done, open && css.expanded)}>
      <button type="button" className={css.head} aria-expanded={open} onClick={onToggle}>
        <span className={css.meta}>
          <span className={q?.severity ? `sev-${q.severity}` : undefined}>
            {[q?.severity && label("severity", q.severity), q?.stage && label("stage", q.stage)].filter(Boolean).join(" · ")}
            {x.chain > 1 && ` · ${t("threads.chain", { n: x.chain })}`}
            {studio && q && <span className={cx(css.id, "mono muted")}>{` · ${q.id}`}</span>}
          </span>
          <span className={css.marks}>
            {x.state !== "open" && <span className={cx(css.word, css[x.state])}>{t(`threads.state.${x.state}`)}</span>}
            {mine && <Tag tone="accent">{t("threads.waitingYou")}</Tag>}
            {!mine && turn && x.state === "open" && (
              <span className={cx(css.word, "muted")}>{t(turn === "studio" ? "threads.waitingStudio" : "threads.waitingAddressee")}</span>
            )}
          </span>
        </span>
        <span className={css.chevron} aria-hidden="true">{open ? "▴" : "▾"}</span>
        <span className={cx(css.text, !open && css.clamp)}>{q?.text ?? ""}</span>
        {!open && last && <span className={cx(css.summary, css.clamp, "muted")}>{last.text}</span>}
      </button>
      {open && children}
    </div>
  );
}
