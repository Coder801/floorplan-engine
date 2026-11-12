// Slide-out panel from the header: project questions, sources (source/) and the project:
// stages, check remarks, results, model. Not about the sheet, so not in the side panel tabs.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { base, enc, getText, type AnswerResult, type ReviewOutcome } from "@/shared/api";
import { REDUCED_MOTION, type DrawerTab } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { kindOf } from "@/shared/files";
import i18n, { label, locale } from "@/shared/i18n";
import type { Answer, QuestionsMemory } from "@/shared/questions";
import ui from "@/shared/styles/ui.module.scss";
import { sourceRows } from "@/shared/sources";
import type { Project } from "@/shared/types";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Heading } from "@/ui/Heading";
import { IconButton } from "@/ui/IconButton";
import { PanelHeader } from "@/ui/PanelHeader";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Text } from "@/ui/Text";
import { Questions } from "@/widgets/Questions";
import css from "./Drawer.module.scss";

interface Props {
  tab: DrawerTab;
  project: Project;
  shownSource: string | null;
  onSource: (file: string) => void;
  busy: boolean;                // an answer is being saved or the project reloaded
  onAnswer: (id: string, answer: Answer | null) => Promise<AnswerResult | null>;
  onReview: (id: string, outcome: ReviewOutcome, comment?: string) => Promise<AnswerResult | null>;
  stages: string[];             // stages of the sheets: where "show" can lead
  onShow: (to: { stage: string; key: string | null }) => void;
  memory: React.MutableRefObject<QuestionsMemory>;  // outlives the panel
  closing: boolean;             // asked to close: the panel slides out to the right
  onClose: () => void;          // close: start sliding out
  onClosed: () => void;         // slid out: remove
}

export function Drawer({ tab, project, shownSource, onSource, busy, onAnswer, onReview, stages, onShow, memory, closing, onClose, onClosed }: Props) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Without animation (reduced motion) there is no animation end, so remove right away
  useEffect(() => { if (closing && REDUCED_MOTION) onClosed(); }, [closing, onClosed]);
  let body: React.ReactNode;
  if (tab === "questions") body = <Questions project={project} busy={busy} onAnswer={onAnswer} onReview={onReview} stages={stages} onShow={onShow} memory={memory} />;
  else if (tab === "sources") body = <Sources project={project} shown={shownSource} onSource={onSource} />;
  else body = <ProjectInfo project={project} />;
  return (
    <section className={cx(css.drawer, closing && css.out)} role="dialog" aria-label={t(`drawer.${tab}`)}
             onAnimationEnd={(ev) => { if (closing && ev.target === ev.currentTarget) onClosed(); }}>
      <PanelHeader title={t(`drawer.${tab}`)}
                   start={<IconButton label={t("common.close")} title={t("common.closeEsc")} onClick={onClose}>→</IconButton>} />
      <div className={ui.panelBody}>{body}</div>
    </section>
  );
}

// Source files: the source/ files and what was parsed from them (intake.yaml, sources)

function Sources({ project: p, shown, onSource }: { project: Project; shown: string | null; onSource: (f: string) => void }) {
  const { t } = useTranslation();
  const list = sourceRows(p.sources, p.parsed);
  if (!list.length) return <Text tone="muted">{t("drawer.noSources")}</Text>;
  const used = list.filter((s) => s.used).length;
  return (
    <>
      <Text size="small" tone="muted">
        {p.parsed ? t("drawer.parsed", { used, total: list.length }) : t("drawer.viewerOld")}
      </Text>
      {list.map((s) => (
        <Card key={s.file} padding="sm" selected={s.file === shown} className={css.card}>
          <Text as="div" size="caps" className={s.used ? "st-ready" : "muted"}>
            {!s.exists ? t("drawer.noFile") : s.used === null ? t("drawer.parseUnknown")
              : s.used ? t("drawer.used") : t("drawer.unused")}
            <span className="muted">{` · ${kindOf(s.file)}`}</span>
          </Text>
          <div className={css.file}>{s.file}</div>
          {s.note && <Text size="small" tone="muted">{s.note}</Text>}
          {s.exists && (
            <div className={css.rowBtns}>
              <Button size="sm" onClick={() => onSource(s.file)}>{t("common.show")}</Button>
              <a href={`${base(p.id)}/source/${enc(s.file)}`} target="_blank" rel="noreferrer">{t("common.openNewTab")}</a>
            </div>
          )}
        </Card>
      ))}
    </>
  );
}

const when = (at: number | null) => (at ? new Date(at * 1000).toLocaleString(locale()) : i18n.t("drawer.notBuilt"));

function ProjectInfo({ project: p }: { project: Project }) {
  const { t } = useTranslation();
  const issues = p.report?.issues || [];
  const [modelFile, setModelFile] = useState<string | null>(null);
  const [text, setText] = useState("…");
  const file = modelFile && p.model.includes(modelFile) ? modelFile : p.model[0] ?? null;
  useEffect(() => {
    if (!file) return;
    let alive = true;
    setText("…");
    getText(`${base(p.id)}/model/${file}`).then((s) => alive && setText(s), (e) => alive && setText((e as Error).message));
    return () => { alive = false; };
  }, [p.id, file]);
  const link = (dir: string, f: string) => (
    <a key={f} href={`${base(p.id)}/${dir}/${enc(f)}`} target="_blank" rel="noreferrer"
       download={/\.(dxf|epd|csv|json)$/i.test(f) ? f.split("/").pop() : undefined}>{f}</a>
  );
  return (
    <>
      <Heading level={3} size="heading" className={css.title}>{p.title}</Heading>
      <div className="small muted"><span className="mono">{`projects/${p.name}`}</span>{` · ${p.built ? t("drawer.built", { when: when(p.built) }) : when(p.built)}`}</div>
      {p.stages.length > 0 && (
        <>
          <h3>{t("drawer.stages")}</h3>
          <div className={css.stages}>
            {p.stages.map((s) => (
              <div key={s.stage} className={css.stage}>
                <div className="small muted">{label("stage", s.stage)}</div>
                <div className={`st-${s.status}`}>{label("status", s.status)}</div>
              </div>
            ))}
          </div>
        </>
      )}
      <h3>{t("drawer.issues", { n: issues.length })}</h3>
      {issues.length ? issues.map((i, k) => (
        <Card key={k} padding="sm" className={css.card}>
          <Text as="div" size="caps" className={i.severity === "error" ? "sev-critical" : "sev-major"}>
            {i.severity === "error" ? t("drawer.error") : t("drawer.warning")}
          </Text>
          <div className="mono muted">{`${i.file}: ${i.path}`}</div>
          <div>{i.message}</div>
        </Card>
      )) : <div className="muted small">{t("drawer.noIssues")}</div>}
      <h3>{t("drawer.results")}</h3>
      {p.files.length ? <div className={cx(css.files, "small")}>{p.files.map((f) => link("out", f))}</div>
        : <div className="muted small">{t("drawer.nothingBuilt")}</div>}
      {file && (
        <>
          <h3>{t("drawer.model")}</h3>
          <SegmentedControl className={css.models} label={t("drawer.model")} value={file} onChange={setModelFile}
                            options={p.model.map((f) => ({ value: f, label: f }))} />
          <pre>{text}</pre>
        </>
      )}
    </>
  );
}
