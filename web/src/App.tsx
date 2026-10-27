// Просмотр собранных проектов: проект из адреса (#имя), листы .epd, боковая панель.
// Данные — API просмотра (service/viewer.py); единственная запись — правки проводки.

import { useCallback, useEffect, useRef, useState } from "react";
import { base, enc, getManifest, getPage, getProject, listProjects } from "./api";
import { THEME_NAME, THEMES, type SideTab, type Theme } from "./consts";
import { applyTheme, remember, remembered, savedTheme } from "./palette";
import { SheetStage, type StageHandle } from "./SheetStage";
import { SidePanel } from "./SidePanel";
import { SourceView } from "./SourceView";
import { resetSelection, view } from "./store";
import type { ManifestPage, Page, Project, ProjectSummary } from "./types";

const fromHash = () => decodeURIComponent(location.hash.slice(1)) || null;

// Не разрешённые вопросы: без ответа и с текстовым ответом, который ещё не разобран
const UNRESOLVED = new Set(["open", "text"]);
export const unresolved = (p: Project | null) =>
  (p?.report ? p.report.questions.filter((q) => UNRESOLVED.has(q.state)).length : 0);

export function App() {
  const [list, setList] = useState<ProjectSummary[]>([]);
  const [current, setCurrent] = useState<string | null>(fromHash);
  const [project, setProject] = useState<Project | null>(null);
  const [pages, setPages] = useState<ManifestPage[]>([]);
  const [sheet, setSheet] = useState<number | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [banners, setBanners] = useState<string[]>([]);
  const [side, setSide] = useState<SideTab>(() => (remembered("side") as SideTab) || "tables");
  const [source, setSource] = useState<string | null>(null);  // файл source/, открытый вместо листа
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const [reloads, setReloads] = useState(0);
  const stage = useRef<StageHandle>(null);

  // Уйти с листа, где есть несохранённые правки трасс, — только с подтверждения
  const confirmLeave = useCallback(() => {
    const n = stage.current?.pending() ?? 0;
    return !n || confirm("Правки трасс не сохранены. Уйти без сохранения?");
  }, []);

  useEffect(() => {
    const onHash = () => {
      if (!confirmLeave()) {  // остаться на листе с несохранёнными правками
        history.replaceState(null, "", `#${encodeURIComponent(current || "")}`);
        return;
      }
      setCurrent(fromHash());
    };
    const onUnload = (ev: BeforeUnloadEvent) => { if (stage.current?.pending()) ev.preventDefault(); };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("beforeunload", onUnload);
    return () => { window.removeEventListener("hashchange", onHash); window.removeEventListener("beforeunload", onUnload); };
  }, [current, confirmLeave]);

  // Тема: системная → светлая → тёмная; холст и 3D перекрашиваются
  useEffect(() => {
    applyTheme(theme);
    view.set({ themeTick: view.get().themeTick + 1 });
  }, [theme]);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const bump = () => view.set({ themeTick: view.get().themeTick + 1 });
    mq.addEventListener("change", bump);
    return () => mq.removeEventListener("change", bump);
  }, []);

  // Проект: список, отчёт, листы; reloads — перечитать после сохранения правок
  useEffect(() => {
    let alive = true;
    setProject(null); setPages([]); setPage(null); setError(null); setSource(null);
    listProjects().then((l) => alive && setList(l)).catch(() => {});
    if (!current) return;
    (async () => {
      try {
        const p = await getProject(current);
        if (!alive) return;
        setProject(p);
        if (!p.artifact) return;
        const m = await getManifest(current);
        if (!alive) return;
        setPages(m.pages);
        setSheet((s) => (m.pages.some((pg) => pg.index === s) ? s : m.pages[0]?.index ?? null));
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    })();
    return () => { alive = false; };
  }, [current, reloads]);

  useEffect(() => {
    if (!current || sheet === null || !pages.length) return;
    let alive = true;
    getPage(current, sheet).then((pg) => {
      if (!alive) return;
      resetSelection();
      setPage(pg);
    }, (e) => alive && setError((e as Error).message));
    return () => { alive = false; };
  }, [current, sheet, pages]);

  const openSheet = (index: number) => {
    if (source) { setSource(null); setSheet(index); return; }
    if (page && index === sheet) return;  // лист уже открыт: правки не терять
    if (confirmLeave()) setSheet(index);
  };
  const showSide = (tab: SideTab) => { setSide(tab); remember("side", tab); };
  const showSource = (file: string) => { if (confirmLeave()) setSource(file); };
  const saved = (notes: string[]) => {
    setBanners(notes.length ? [`wiring.yaml: ${notes.join("; ")}`] : []);
    setReloads((n) => n + 1);
  };

  const openQs = unresolved(project);
  const warn = project?.stale
    ? `YAML правили после сборки — листы устарели: uv run shtroba build projects/${project.name}`
    : project && !project.report ? `Проект не собран: uv run shtroba build projects/${project.name}` : null;

  let main: React.ReactNode;
  if (!current) main = <div className="empty">Выберите проект</div>;
  else if (error) main = <div className="error">{error}</div>;
  else if (source && project) main = <SourceView project={project} file={source} onBack={() => setSource(null)} />;
  else if (project && !project.artifact) main = <div className="empty">Нет out/project.epd — листы появятся после build</div>;
  else if (page && project) {
    main = <SheetStage ref={stage} key={`${current}/${sheet}/${reloads}`} page={page} project={project.name}
                       onSaved={saved} onBanner={(b) => setBanners([b])} />;
  }

  return (
    <>
      <header>
        <div className="logo" aria-hidden="true">ep</div>
        <label className="small muted" htmlFor="project">Проект</label>
        <select id="project" value={current || ""}
                onChange={(e) => { location.hash = encodeURIComponent(e.target.value); }}>
          <option value="">{list.length ? "— выберите —" : "нет проектов"}</option>
          {list.map((p) => (
            <option key={p.name} value={p.name}>
              {`${p.title}${p.open_questions ? ` · вопросов ${p.open_questions}` : ""}${p.stale ? " · устарел" : ""}`}
            </option>
          ))}
        </select>
        <nav className="tabs" aria-label="Листы">
          {pages.map((pg) => (
            <button key={pg.index} className={pg.index === sheet && !source ? "on" : undefined}
                    onClick={() => openSheet(pg.index)}>{pg.name}</button>
          ))}
        </nav>
        <div className="spacer" />
        <span>
          {openQs > 0 && <button className="pill" onClick={() => showSide("questions")}>Открытых вопросов: {openQs}</button>}
        </span>
        <button title="Тема: системная → светлая → тёмная"
                onClick={() => {
                  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
                  remember("theme", next); setTheme(next);
                }}>{THEME_NAME[theme]}</button>
        <button disabled={!page || !!source} title="Весь лист с таблицами и штампом, не больше A3 150 dpi"
                onClick={() => page && stage.current?.downloadPng(`${current}-${page.name}.png`)}>PNG для альбома</button>
        {project?.dxf && current && (
          <a className="btn-link" href={`${base(current)}/out/${enc(project.dxf)}`} download={project.dxf}>Скачать DXF</a>
        )}
      </header>
      <div>
        {warn && <div className="banner">{warn}</div>}
        {banners.map((b) => <div key={b} className="banner">{b}</div>)}
      </div>
      <div className="layout">
        <main id="stage">{main}</main>
        <SidePanel tab={side} onTab={showSide} project={project} page={source ? null : page}
                   shownSource={source} onSource={showSource} />
      </div>
    </>
  );
}
