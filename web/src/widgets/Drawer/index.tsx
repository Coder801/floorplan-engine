// Выдвижная панель из шапки: вопросы проекта, исходники (source/) и проект — этапы,
// замечания проверки, результаты, модель. Не про лист, поэтому не во вкладках боковой панели.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { base, enc, getText } from "@/shared/api";
import { REDUCED_MOTION, type DrawerTab } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { kindOf } from "@/shared/files";
import i18n, { label, locale } from "@/shared/i18n";
import ui from "@/shared/styles/ui.module.scss";
import type { Project } from "@/shared/types";
import css from "./Drawer.module.scss";

interface Props {
  tab: DrawerTab;
  project: Project;
  shownSource: string | null;
  onSource: (file: string) => void;
  closing: boolean;             // попросили закрыть — панель уезжает вправо
  onClose: () => void;          // закрыть: запустить уезжание
  onClosed: () => void;         // уехала — убрать
}

export function Drawer({ tab, project, shownSource, onSource, closing, onClose, onClosed }: Props) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Без анимации (уменьшение движения) конца анимации не будет — убрать сразу
  useEffect(() => { if (closing && REDUCED_MOTION) onClosed(); }, [closing, onClosed]);
  let body: React.ReactNode;
  if (tab === "questions") body = <Questions project={project} />;
  else if (tab === "sources") body = <Sources project={project} shown={shownSource} onSource={onSource} />;
  else body = <ProjectInfo project={project} />;
  return (
    <section className={cx(css.drawer, closing && css.out)} role="dialog" aria-label={t(`drawer.${tab}`)}
             onAnimationEnd={(ev) => { if (closing && ev.target === ev.currentTarget) onClosed(); }}>
      <div className={ui.panelHead}>
        <button aria-label={t("common.close")} title={t("common.closeEsc")} onClick={onClose}>→</button>
        <h2>{t(`drawer.${tab}`)}</h2>
      </div>
      <div className={ui.panelBody}>{body}</div>
    </section>
  );
}

function answerText(a: unknown): string {
  if (a === undefined) return "";
  if (a && typeof a === "object") {
    const o = a as Record<string, unknown>;
    if (o.accept) return i18n.t("drawer.keepAssumption");
    if ("text" in o) return `«${o.text}»${o.resolved ? i18n.t("drawer.parsedMark") : ""}`;
    return JSON.stringify(a);
  }
  return String(a);
}

function Questions({ project: p }: { project: Project }) {
  const { t } = useTranslation();
  if (!p.report) return <div className="muted">{t("drawer.noReport")}</div>;
  const qs = p.report.questions;
  if (!qs.length) return <div className="muted">{t("drawer.noQuestions")}</div>;
  const order: Record<string, number> = { open: 0, text: 1, answered: 2, accepted: 3 };
  return (
    <>
      {[...qs].sort((a, b) => (order[a.state] ?? 9) - (order[b.state] ?? 9)).map((q) => (
        <div key={q.id} className={cx(css.card, q.state !== "open" && css.done)}>
          <div className={cx(css.sev, `sev-${q.severity}`)}>
            {`${label("severity", q.severity)} · ${label("stage", q.stage)}`}
            <span className="mono muted">{` · ${q.id}`}</span>
          </div>
          <div className={css.text}>{q.text}</div>
          {q.assumption !== undefined && (
            <div className="small muted">{t("drawer.inModel", { value: `${String(q.assumption)}${q.unit ? " " + q.unit : ""}` })}</div>
          )}
          {p.answers[q.id] !== undefined && <div className="small">{t("drawer.answer", { value: answerText(p.answers[q.id]) })}</div>}
          <div className={`small ${q.state === "open" ? "sev-major" : "muted"}`}>{label("qstate", q.state)}</div>
          {q.target && <div className="mono muted">{q.target}</div>}
        </div>
      ))}
    </>
  );
}

// Исходные ресурсы: файлы source/ и что из них разобрано (intake.yaml, sources)

function Sources({ project: p, shown, onSource }: { project: Project; shown: string | null; onSource: (f: string) => void }) {
  const { t } = useTranslation();
  const parsed = new Map((p.parsed || []).map((s) => [s.file, s.note]));
  const files = [...new Set([...p.sources, ...parsed.keys()])];
  if (!files.length) return <div className="muted">{t("drawer.noSources")}</div>;
  // Старый сервер без parsed — о разборе неизвестно, а не «не использован»
  const list = files.map((f) => ({ file: f, used: p.parsed ? parsed.has(f) : null, note: parsed.get(f) || "",
                                   exists: p.sources.includes(f) }));
  const used = list.filter((s) => s.used).length;
  return (
    <>
      <div className={cx(css.lead, "small muted")}>
        {p.parsed ? t("drawer.parsed", { used, total: list.length }) : t("drawer.viewerOld")}
      </div>
      {list.map((s) => (
        <div key={s.file} className={cx(css.card, s.file === shown && css.lit)}>
          <div className={cx(css.sev, s.used ? "st-ready" : "muted")}>
            {!s.exists ? t("drawer.noFile") : s.used === null ? t("drawer.parseUnknown")
              : s.used ? t("drawer.used") : t("drawer.unused")}
            <span className="muted">{` · ${kindOf(s.file)}`}</span>
          </div>
          <div className={css.file}>{s.file}</div>
          {s.note && <div className="small muted">{s.note}</div>}
          {s.exists && (
            <div className={css.rowBtns}>
              <button onClick={() => onSource(s.file)}>{t("common.show")}</button>
              <a href={`${base(p.name)}/source/${enc(s.file)}`} target="_blank" rel="noreferrer">{t("common.openNewTab")}</a>
            </div>
          )}
        </div>
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
    getText(`${base(p.name)}/model/${file}`).then((s) => alive && setText(s), (e) => alive && setText((e as Error).message));
    return () => { alive = false; };
  }, [p.name, file]);
  const link = (dir: string, f: string) => (
    <a key={f} href={`${base(p.name)}/${dir}/${enc(f)}`} target="_blank" rel="noreferrer"
       download={/\.(dxf|epd|csv|json)$/i.test(f) ? f.split("/").pop() : undefined}>{f}</a>
  );
  return (
    <>
      <h3>{p.title}</h3>
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
        <div key={k} className={css.card}>
          <div className={cx(css.sev, i.severity === "error" ? "sev-critical" : "sev-major")}>
            {i.severity === "error" ? t("drawer.error") : t("drawer.warning")}
          </div>
          <div className="mono muted">{`${i.file}: ${i.path}`}</div>
          <div>{i.message}</div>
        </div>
      )) : <div className="muted small">{t("drawer.noIssues")}</div>}
      <h3>{t("drawer.results")}</h3>
      {p.files.length ? <div className={cx(css.files, "small")}>{p.files.map((f) => link("out", f))}</div>
        : <div className="muted small">{t("drawer.nothingBuilt")}</div>}
      {file && (
        <>
          <h3>{t("drawer.model")}</h3>
          <div className={cx(ui.segmented, css.models)}>
            {p.model.map((f) => (
              <button key={f} className={cx(f === file && ui.on)} onClick={() => setModelFile(f)}>{f}</button>
            ))}
          </div>
          <pre>{text}</pre>
        </>
      )}
    </>
  );
}
