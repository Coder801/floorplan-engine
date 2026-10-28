// Выдвижная панель из шапки: вопросы проекта, исходники (source/) и проект — этапы,
// замечания проверки, результаты, модель. Не про лист, поэтому не во вкладках боковой панели.

import { useEffect, useState } from "react";
import { base, enc, getText } from "./api";
import { DRAWER, QSTATE, REDUCED_MOTION, SEVERITY, STAGE, STATUS, type DrawerTab } from "./consts";
import { cx } from "./cx";
import css from "./Drawer.module.scss";
import ui from "./styles/ui.module.scss";
import type { Project } from "./types";

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
    <section className={cx(css.drawer, closing && css.out)} role="dialog" aria-label={DRAWER[tab]}
             onAnimationEnd={(ev) => { if (closing && ev.target === ev.currentTarget) onClosed(); }}>
      <div className={ui.panelHead}>
        <button aria-label="Закрыть" title="Закрыть (Esc)" onClick={onClose}>→</button>
        <h2>{DRAWER[tab]}</h2>
      </div>
      <div className={ui.panelBody}>{body}</div>
    </section>
  );
}

function answerText(a: unknown): string {
  if (a === undefined) return "";
  if (a && typeof a === "object") {
    const o = a as Record<string, unknown>;
    if (o.accept) return "оставить допущение";
    if ("text" in o) return `«${o.text}»${o.resolved ? " (разобран)" : ""}`;
    return JSON.stringify(a);
  }
  return String(a);
}

function Questions({ project: p }: { project: Project }) {
  if (!p.report) return <div className="muted">Отчёта нет — проект не собран</div>;
  const qs = p.report.questions;
  if (!qs.length) return <div className="muted">Вопросов нет</div>;
  const order: Record<string, number> = { open: 0, text: 1, answered: 2, accepted: 3 };
  return (
    <>
      {[...qs].sort((a, b) => (order[a.state] ?? 9) - (order[b.state] ?? 9)).map((q) => (
        <div key={q.id} className={cx(css.card, q.state !== "open" && css.done)}>
          <div className={cx(css.sev, `sev-${q.severity}`)}>
            {`${SEVERITY[q.severity] || q.severity} · ${STAGE[q.stage] || q.stage}`}
            <span className="mono muted">{` · ${q.id}`}</span>
          </div>
          <div className={css.text}>{q.text}</div>
          {q.assumption !== undefined && (
            <div className="small muted">{`В модели: ${String(q.assumption)}${q.unit ? " " + q.unit : ""}`}</div>
          )}
          {p.answers[q.id] !== undefined && <div className="small">Ответ: {answerText(p.answers[q.id])}</div>}
          <div className={`small ${q.state === "open" ? "sev-major" : "muted"}`}>{QSTATE[q.state] || q.state}</div>
          {q.target && <div className="mono muted">{q.target}</div>}
        </div>
      ))}
    </>
  );
}

// Исходные ресурсы: файлы source/ и что из них разобрано (intake.yaml, sources)
const KIND: [RegExp, string][] = [[/\.pdf$/i, "pdf"], [/\.(png|jpe?g|webp|gif)$/i, "image"], [/\.(md|txt|ya?ml|csv)$/i, "text"]];
export const kindOf = (f: string) => (KIND.find(([re]) => re.test(f)) || [null, "file"])[1];

function Sources({ project: p, shown, onSource }: { project: Project; shown: string | null; onSource: (f: string) => void }) {
  const parsed = new Map((p.parsed || []).map((s) => [s.file, s.note]));
  const files = [...new Set([...p.sources, ...parsed.keys()])];
  if (!files.length) return <div className="muted">В source/ нет файлов</div>;
  // Старый сервер без parsed — о разборе неизвестно, а не «не использован»
  const list = files.map((f) => ({ file: f, used: p.parsed ? parsed.has(f) : null, note: parsed.get(f) || "",
                                   exists: p.sources.includes(f) }));
  const used = list.filter((s) => s.used).length;
  return (
    <>
      <div className={cx(css.lead, "small muted")}>
        {p.parsed ? `Разобрано ${used} из ${list.length}. Отметки — из intake.yaml (sources).`
          : "Сервер просмотра устарел — перезапустите floorplan-engine view, чтобы увидеть, что разобрано."}
      </div>
      {list.map((s) => (
        <div key={s.file} className={cx(css.card, s.file === shown && css.lit)}>
          <div className={cx(css.sev, s.used ? "st-ready" : "muted")}>
            {!s.exists ? "нет файла в source/" : s.used === null ? "разбор неизвестен"
              : s.used ? "использован в разборе" : "не использован"}
            <span className="muted">{` · ${kindOf(s.file)}`}</span>
          </div>
          <div className={css.file}>{s.file}</div>
          {s.note && <div className="small muted">{s.note}</div>}
          {s.exists && (
            <div className={css.rowBtns}>
              <button onClick={() => onSource(s.file)}>Показать</button>
              <a href={`${base(p.name)}/source/${enc(s.file)}`} target="_blank" rel="noreferrer">Открыть в новой вкладке</a>
            </div>
          )}
        </div>
      ))}
    </>
  );
}

const when = (t: number | null) => (t ? new Date(t * 1000).toLocaleString("ru") : "не собран");

function ProjectInfo({ project: p }: { project: Project }) {
  const issues = p.report?.issues || [];
  const [modelFile, setModelFile] = useState<string | null>(null);
  const [text, setText] = useState("…");
  const file = modelFile && p.model.includes(modelFile) ? modelFile : p.model[0] ?? null;
  useEffect(() => {
    if (!file) return;
    let alive = true;
    setText("…");
    getText(`${base(p.name)}/model/${file}`).then((t) => alive && setText(t), (e) => alive && setText((e as Error).message));
    return () => { alive = false; };
  }, [p.name, file]);
  const link = (dir: string, f: string) => (
    <a key={f} href={`${base(p.name)}/${dir}/${enc(f)}`} target="_blank" rel="noreferrer"
       download={/\.(dxf|epd|csv|json)$/i.test(f) ? f.split("/").pop() : undefined}>{f}</a>
  );
  return (
    <>
      <h3>{p.title}</h3>
      <div className="small muted"><span className="mono">{`projects/${p.name}`}</span>{` · собран ${when(p.built)}`}</div>
      {p.stages.length > 0 && (
        <>
          <h3>Этапы</h3>
          <div className={css.stages}>
            {p.stages.map((s) => (
              <div key={s.stage} className={css.stage}>
                <div className="small muted">{STAGE[s.stage] || s.stage}</div>
                <div className={`st-${s.status}`}>{STATUS[s.status] || s.status}</div>
              </div>
            ))}
          </div>
        </>
      )}
      <h3>{`Замечания проверки · ${issues.length}`}</h3>
      {issues.length ? issues.map((i, k) => (
        <div key={k} className={css.card}>
          <div className={cx(css.sev, i.severity === "error" ? "sev-critical" : "sev-major")}>
            {i.severity === "error" ? "ошибка" : "предупреждение"}
          </div>
          <div className="mono muted">{`${i.file}: ${i.path}`}</div>
          <div>{i.message}</div>
        </div>
      )) : <div className="muted small">Замечаний нет</div>}
      <h3>Результаты (out/)</h3>
      {p.files.length ? <div className={cx(css.files, "small")}>{p.files.map((f) => link("out", f))}</div>
        : <div className="muted small">Пока ничего не собрано</div>}
      {file && (
        <>
          <h3>Модель</h3>
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
