// Боковая панель: таблицы листа (связь строка ↔ объекты), слои, вопросы, исходники, проект

import { useEffect, useMemo, useState } from "react";
import { base, enc, getText } from "./api";
import { unresolved } from "./App";
import { LAYER, QSTATE, SEVERITY, SIDE, STAGE, STATUS, SHEET_ONLY, type SideTab } from "./consts";
import { expand } from "./page";
import { refreshPalette, screenColor } from "./palette";
import { useView, view } from "./store";
import type { Page, Project, SideTable } from "./types";

interface Props {
  tab: SideTab;
  onTab: (tab: SideTab) => void;
  project: Project | null;
  page: Page | null;
  shownSource: string | null;
  onSource: (file: string) => void;
}

export function SidePanel({ tab, onTab, project, page, shownSource, onSource }: Props) {
  let body: React.ReactNode;
  if (!project) body = <div className="muted">Проект не открыт</div>;
  else if (tab === "tables") body = <Tables page={page} />;
  else if (tab === "layers") body = <Layers page={page} />;
  else if (tab === "questions") body = <Questions project={project} />;
  else if (tab === "sources") body = <Sources project={project} shown={shownSource} onSource={onSource} />;
  else body = <ProjectInfo project={project} />;
  const open = unresolved(project);
  return (
    <aside>
      <div className="side-tabs" role="tablist">
        {(Object.keys(SIDE) as SideTab[]).map((k) => {
          const n = k === "questions" ? open : 0;
          return (
            <button key={k} role="tab" className={k === tab ? "on" : undefined} aria-selected={k === tab}
                    aria-label={n ? `${SIDE[k]}: ${n}` : undefined} onClick={() => onTab(k)}>
              <span className="tab-name">{SIDE[k]}{n > 0 && <span className="count" aria-hidden="true">{n}</span>}</span>
            </button>
          );
        })}
      </div>
      <div className="side-body">{body}</div>
    </aside>
  );
}

// Таблицы листа: строка со ссылками на объекты подсвечивается при наведении на объект
// и сама подсвечивает их на чертеже
function Tables({ page }: { page: Page | null }) {
  const hover = useView((s) => s.hover);
  const [rowHover, setRowHover] = useState<string | null>(null);
  const hoverKeys = useMemo(() => new Set(hover ? expand(hover) : []), [hover]);

  // Объект под курсором на чертеже — прокрутить панель к его первой строке
  useEffect(() => {
    if (hover) document.querySelector(".side-body tr.lit")?.scrollIntoView({ block: "nearest" });
  }, [hover]);

  if (!page) return <div className="muted">Лист не открыт</div>;
  const tables = page.tables || [];
  if (!tables.length) return <div className="muted">В артефакте нет таблиц для панели — пересоберите проект (build)</div>;
  return (
    <>
      {tables.map((t, ti) => (
        <TableView key={ti} t={t} id={`${ti}`} rowHover={rowHover} hoverKeys={hoverKeys}
                   onRow={(rid, keys) => { setRowHover(rid); view.set({ lit: keys }); }} />
      ))}
    </>
  );
}

function TableView({ t, id, rowHover, hoverKeys, onRow }: {
  t: SideTable; id: string; rowHover: string | null; hoverKeys: Set<string>;
  onRow: (rid: string | null, keys: Set<string> | null) => void;
}) {
  const al = (i: number) => (t.align[i] === "left" ? undefined : "c");
  return (
    <>
      <h3>{t.title}</h3>
      <table className="data">
        <thead><tr>{t.columns.map((c, i) => <th key={i} className={al(i)}>{c}</th>)}</tr></thead>
        <tbody>
          {t.rows.map((r, ri) => {
            const rid = `${id}/${ri}`;
            const lit = rid === rowHover || (!!r.keys && r.keys.some((k) => hoverKeys.has(k)));
            const cls = [r.section ? "section" : "", r.keys ? "linked" : "", lit ? "lit" : ""].join(" ").trim();
            return (
              <tr key={ri} className={cls || undefined}
                  onPointerEnter={r.keys ? () => onRow(rid, new Set(r.keys)) : undefined}
                  onPointerLeave={r.keys ? () => onRow(null, null) : undefined}>
                {r.cells.map((c, i) => (
                  <td key={i} className={i === 0 && r.color ? "mark" : al(i)}>
                    {/* Группа щита — кружок её цвета, как линии на чертеже */}
                    {i === 0 && r.color && <span className="dot" style={{ background: r.color }} aria-hidden="true" />}
                    {c}
                  </td>
                ))}
              </tr>
            );
          })}
          {t.total && <tr className="total">{t.total.map((c, i) => <td key={i} className={al(i)}>{c}</td>)}</tr>}
        </tbody>
      </table>
      {t.notes && <ul className="notes">{t.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
    </>
  );
}

function Layers({ page }: { page: Page | null }) {
  const hidden = useView((s) => s.hidden);
  useView((s) => s.themeTick);
  if (!page) return <div className="muted">Лист не открыт</div>;
  refreshPalette();
  const colors = new Map<string, string>();
  for (const it of page.items) if (!SHEET_ONLY.has(it.l) && !colors.has(it.l)) colors.set(it.l, it.c);
  const toggle = (l: string, on: boolean) => {
    const next = new Set(hidden);
    if (on) next.delete(l); else next.add(l);
    view.set({ hidden: next });
  };
  return (
    <div className="layers">
      {[...colors.keys()].sort().map((l) => (
        <label key={l} htmlFor={`layer-${l}`}>
          <input type="checkbox" id={`layer-${l}`} checked={!hidden.has(l)}
                 onChange={(e) => toggle(l, e.target.checked)} />
          <span aria-hidden="true" style={{ width: 14, height: 4, flex: "none", background: screenColor(colors.get(l)!) }} />
          {LAYER[l] || l}
          <span className="code mono">{l}</span>
        </label>
      ))}
    </div>
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
        <div key={q.id} className={`card${q.state === "open" ? "" : " done"}`}>
          <div className={`sev sev-${q.severity}`}>
            {`${SEVERITY[q.severity] || q.severity} · ${STAGE[q.stage] || q.stage}`}
            <span className="mono muted">{` · ${q.id}`}</span>
          </div>
          <div style={{ margin: "4px 0" }}>{q.text}</div>
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
      <div className="small muted" style={{ marginBottom: 10 }}>
        {p.parsed ? `Разобрано ${used} из ${list.length}. Отметки — из intake.yaml (sources).`
          : "Сервер просмотра устарел — перезапустите floorplan-engine view, чтобы увидеть, что разобрано."}
      </div>
      {list.map((s) => (
        <div key={s.file} className={`card${s.file === shown ? " lit" : ""}`}>
          <div className={`sev ${s.used ? "st-ready" : "muted"}`}>
            {!s.exists ? "нет файла в source/" : s.used === null ? "разбор неизвестен"
              : s.used ? "использован в разборе" : "не использован"}
            <span className="muted">{` · ${kindOf(s.file)}`}</span>
          </div>
          <div style={{ margin: "4px 0", wordBreak: "break-word" }}>{s.file}</div>
          {s.note && <div className="small muted">{s.note}</div>}
          {s.exists && (
            <div className="row-btns">
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
          <div className="stages">
            {p.stages.map((s) => (
              <div key={s.stage}>
                <div className="small muted">{STAGE[s.stage] || s.stage}</div>
                <div className={`st-${s.status}`}>{STATUS[s.status] || s.status}</div>
              </div>
            ))}
          </div>
        </>
      )}
      <h3>{`Замечания проверки · ${issues.length}`}</h3>
      {issues.length ? issues.map((i, k) => (
        <div key={k} className="card">
          <div className={`sev ${i.severity === "error" ? "sev-critical" : "sev-major"}`}>
            {i.severity === "error" ? "ошибка" : "предупреждение"}
          </div>
          <div className="mono muted">{`${i.file}: ${i.path}`}</div>
          <div>{i.message}</div>
        </div>
      )) : <div className="muted small">Замечаний нет</div>}
      <h3>Результаты (out/)</h3>
      {p.files.length ? <div className="files small">{p.files.map((f) => link("out", f))}</div>
        : <div className="muted small">Пока ничего не собрано</div>}
      {file && (
        <>
          <h3>Модель</h3>
          <div className="tabs" style={{ marginBottom: 8 }}>
            {p.model.map((f) => (
              <button key={f} className={f === file ? "on" : undefined} onClick={() => setModelFile(f)}>{f}</button>
            ))}
          </div>
          <pre>{text}</pre>
        </>
      )}
    </>
  );
}
