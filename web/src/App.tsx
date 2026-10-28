// Просмотр собранных проектов: проект из адреса (#имя), листы .epd, боковая панель.
// Данные — API просмотра (service/viewer.py); единственная запись — правки проводки.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { base, enc, getManifest, getPage, getProject, listProjects } from "./api";
import { DRAWER, SIDE, type DrawerTab, type SideTab, type Theme } from "./consts";
import css from "./App.module.scss";
import { Boundary } from "./Boundary";
import { DownloadMenu } from "./DownloadMenu";
import { Drawer } from "./Drawer";
import { cx } from "./cx";
import { applyTheme, remember, remembered, savedTheme } from "./palette";
import { Logo } from "./Logo";
import { PanelStage } from "./PanelStage";
import { ProjectsMenu } from "./ProjectsMenu";
import { buildDrawing, DRAWING_STAGES } from "./sheet/drawing";
import { downloadSheetPng } from "./sheet/paint";
import { wallPages, wallSheet } from "./sheet/walls";
import { SheetStage, type StageHandle } from "./SheetStage";
import { type Account, Settings } from "./Settings";
import { SidePanel } from "./SidePanel";
import { SourceView } from "./SourceView";
import ui from "./styles/ui.module.scss";
import { WallMap } from "./WallMap";
import { Welcome } from "./Welcome";
import { resetSelection, view } from "./store";
import { sheetTabs, tabOf, VIEWS } from "./tabs";
import type { ManifestPage, Page, Project, ProjectSummary, Scene } from "./types";
import { watchBuild } from "./version";

const fromHash = () => decodeURIComponent(location.hash.slice(1)) || null;

// Не разрешённые вопросы: без ответа и с текстовым ответом, который ещё не разобран
const UNRESOLVED = new Set(["open", "text"]);
export const unresolved = (p: Project | null) =>
  (p?.report ? p.report.questions.filter((q) => UNRESOLVED.has(q.state)).length : 0);

// account — кто вошёл (Gate, для настроек); вход выключен — null
export function App({ account = null }: { account?: Account | null }) {
  const [list, setList] = useState<ProjectSummary[]>([]);
  const [current, setCurrent] = useState<string | null>(fromHash);
  const [project, setProject] = useState<Project | null>(null);
  const [pages, setPages] = useState<ManifestPage[]>([]);
  const [sheet, setSheet] = useState<number | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [loaded, setLoaded] = useState<number | null>(null);  // лист, чья страница сейчас в page
  const [drawn, setDrawn] = useState<Page[]>([]);  // листы чертежа, на котором стоит page
  const [elevs, setElevs] = useState<{ index: number; page: Page }[]>([]);  // листы развёрток
  const [scene, setScene] = useState<Scene | null>(null);  // 3D-сцена — для мини-схемы развёртки
  const [wallKey, setWallKey] = useState<string | null>(null);  // открытая развёртка
  const cache = useRef(new Map<number, Promise<Page>>());  // страницы проекта — один раз
  const [error, setError] = useState<string | null>(null);
  const [banners, setBanners] = useState<string[]>([]);
  const [side, setSide] = useState<SideTab>(() => {
    const t = remembered("side");
    return t && t in SIDE ? (t as SideTab) : "tables";
  });
  const [drawer, setDrawer] = useState<DrawerTab | null>(null);  // вопросы, исходники, проект
  const [closing, setClosing] = useState(false);                // панель уезжает
  const [menu, setMenu] = useState<"open" | "closing" | null>(null);  // меню проектов слева
  const [more, setMore] = useState(false);  // телефон: действия шапки — меню «⋯»
  const [source, setSource] = useState<string | null>(null);  // файл source/, открытый вместо листа
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const [reloads, setReloads] = useState(0);
  const [outdated, setOutdated] = useState(false);  // после открытия вкладки выложили новую версию
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

  useEffect(() => watchBuild(() => setOutdated(true)), []);

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
    setProject(null); setPages([]); setPage(null); setLoaded(null); setDrawn([]); setElevs([]); setScene(null); setWallKey(null);
    setError(null); setSource(null);
    cache.current = new Map();
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
        // Ведомость точек — для печати; в просмотре она в боковой панели листа электрики
        setPages(m.pages.filter((pg) => pg.stage !== "points"));
        setSheet((s) => (m.pages.some((pg) => pg.index === s) ? s : m.pages[0]?.index ?? null));
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    })();
    return () => { alive = false; };
  }, [current, reloads]);

  // Листы с планом (план, электрика, освещение, проводка) — один чертёж: грузятся вместе,
  // вкладка между ними — другие слои того же чертежа (sheet/drawing.ts)
  const drawingSheets = useMemo(
    () => pages.filter((pg) => pg.stage && DRAWING_STAGES.has(pg.stage)).map((pg) => pg.index), [pages]);
  // Развёртки — постранично по стенам: листы вкладки грузятся вместе, и с ними лист со сценой
  const elevSheets = useMemo(() => pages.filter((pg) => pg.stage === "elevations").map((pg) => pg.index), [pages]);
  const sceneSheet = pages.find((pg) => pg.stage === "wiring")?.index;

  useEffect(() => {
    if (!current || sheet === null || !pages.length) return;
    let alive = true;
    const load = (i: number) => {
      let p = cache.current.get(i);
      if (!p) {
        p = getPage(current, i);
        cache.current.set(i, p);
        p.catch(() => cache.current.delete(i));
      }
      return p;
    };
    const walls = elevSheets.includes(sheet);
    const want = drawingSheets.includes(sheet) ? drawingSheets : walls ? elevSheets : [sheet];
    // Сцена мини-схемы — не обязательна: не загрузилась — развёртки без схемы
    if (walls && sceneSheet !== undefined) {
      load(sceneSheet).then((pg) => alive && setScene(pg.scene ?? null), () => {});
    }
    Promise.all(want.map(load)).then((pgs) => {
      if (!alive) return;
      if (walls) setElevs(want.map((index, i) => ({ index, page: pgs[i] })));
      // Вкладка того же чертежа — 3D остаётся (меняются слои), другой лист — сначала план
      const was = drawnRef.current;
      resetSelection(pgs.length > 1 && was.length === pgs.length && was.every((p, i) => p === pgs[i]));
      setPage(pgs[want.indexOf(sheet)]);
      setLoaded(sheet);
      // Те же страницы — тот же чертёж: холст, масштаб и сдвиг остаются
      const own = walls ? [pgs[want.indexOf(sheet)]] : pgs;
      setDrawn((prev) => (prev.length === own.length && prev.every((p, i) => p === own[i]) ? prev : own));
    }, (e) => alive && setError((e as Error).message));
    return () => { alive = false; };
  }, [current, sheet, pages, drawingSheets, elevSheets, sceneSheet]);

  const sheetDrawing = useMemo(() => (drawn.length ? buildDrawing(drawn) : null), [drawn]);
  // Развёртка стены: тот же лист, видовой экран — её габарит
  const walls = useMemo(() => wallPages(elevs), [elevs]);
  const wall = walls.find((w) => w.key === wallKey && w.sheet === sheet) ?? walls.find((w) => w.sheet === sheet) ?? null;
  const wallPage = useMemo(() => (wall && page && elevSheets.includes(loaded ?? -1) ? wallSheet(page, wall) : null),
    [wall, page, elevSheets, loaded]);
  const wallDrawing = useMemo(() => (wallPage ? buildDrawing([wallPage]) : null), [wallPage]);
  const drawing = wallDrawing ?? sheetDrawing;
  const drawnRef = useRef(drawn);
  drawnRef.current = drawn;

  // Другой лист — сразу без подсказки, 3D и правки, не дожидаясь загрузки страницы
  const openSheet = (index: number) => {
    if (source) { setSource(null); resetSelection(); setSheet(index); return; }
    if (page && index === sheet) {  // лист уже открыт: правки не терять, из 3D — на лист
      if (view.get().show3d) view.set({ show3d: false, pinned: null, selected: null, neighbors: null, tip: null });
      return;
    }
    const sameDrawing = sheet !== null && drawingSheets.includes(sheet) && drawingSheets.includes(index);
    if (confirmLeave()) { resetSelection(sameDrawing); setSheet(index); }
  };
  const showSide = (tab: SideTab) => { setSide(tab); remember("side", tab); };
  // Та же кнопка — закрыть (панель уезжает), другая — открыть её
  const toggleDrawer = (tab: DrawerTab) => {
    if (drawer === tab && !closing) setClosing(true);
    else { setDrawer(tab); setClosing(false); }
  };
  const closeDrawer = useCallback(() => setClosing(true), []);
  const closeMenu = useCallback(() => setMenu((m) => (m ? "closing" : m)), []);
  const menuClosed = useCallback(() => setMenu(null), []);
  const drawerClosed = useCallback(() => { setDrawer(null); setClosing(false); }, []);
  const showSource = (file: string) => { if (confirmLeave()) setSource(file); };
  const saved = (notes: string[]) => {
    setBanners(notes.length ? [`wiring.yaml: ${notes.join("; ")}`] : []);
    setReloads((n) => n + 1);
  };

  // Продолжения (развёртки) — одна вкладка, страницы — внутри чертежа; электрика, освещение
  // и проводка — одна вкладка, вид — переключателем справа (SidePanel)
  const tabs = sheetTabs(pages);
  const tab = source ? null : tabOf(tabs, sheet);
  const stageOf = (i: number) => pages.find((pg) => pg.index === i)?.stage ?? "";
  const views = tab?.views ? tab.pages.map((i) => ({ index: i, label: VIEWS[stageOf(i)] ?? stageOf(i) })) : null;
  // Вкладка с видами открывается на последнем выбранном виде
  const [lastView, setLastView] = useState(() => remembered("view") || "electrical");
  useEffect(() => {
    const st = pages.find((pg) => pg.index === sheet)?.stage;
    if (st && st in VIEWS) { setLastView(st); remember("view", st); }
  }, [sheet, pages]);
  const tabTarget = (t: (typeof tabs)[number]) =>
    (t === tab && sheet !== null ? sheet : t.views ? t.pages.find((i) => stageOf(i) === lastView) ?? t.pages[0] : t.pages[0]);
  const at = tab && sheet !== null ? tab.pages.indexOf(sheet) : -1;
  // Страницы вкладки развёрток — стены, а не листы
  const wallAt = wall ? walls.indexOf(wall) : -1;
  const turn = (step: number) => {
    if (wallAt >= 0) {
      const next = walls[wallAt + step];
      if (!next) return;
      setWallKey(next.key);
      if (next.sheet !== sheet) openSheet(next.sheet);
      else resetSelection();
      return;
    }
    if (tab && at >= 0) {
      const next = tab.pages[at + step];
      if (next !== undefined) openSheet(next);
    }
  };

  // PageUp / PageDown — соседняя страница, если у листа их несколько
  const turnRef = useRef(turn);
  turnRef.current = turn;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea, select")) return;
      if (e.key === "PageDown") { e.preventDefault(); turnRef.current(1); }
      if (e.key === "PageUp") { e.preventDefault(); turnRef.current(-1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openQs = unresolved(project);
  const warn = project?.stale
    ? `YAML правили после сборки — листы устарели: uv run floorplan-engine build projects/${project.name}`
    : project && !project.report ? `Проект не собран: uv run floorplan-engine build projects/${project.name}` : null;

  // Пока грузится проект или лист — прелоадер поверх чертежа (прежний лист виден под ним)
  const loading = !!current && !error && !source && (!project || (!!project.artifact && loaded !== sheet));

  let main: React.ReactNode;
  if (!current) main = <div className={ui.empty}>Выберите проект</div>;
  else if (error) main = <div className={ui.error}>{error}</div>;
  else if (source && project) main = <SourceView project={project} file={source} onBack={() => setSource(null)} />;
  else if (project && !project.artifact) main = <div className={ui.empty}>Нет out/project.epd — листы появятся после build</div>;
  else if (page && project && page.panel) {
    main = <PanelStage ref={stage} page={page} panel={page.panel} />;
  } else if (page && project && !page.items?.length) {
    main = <div className={ui.error}>На листе {page.name} нечего рисовать — пересоберите проект или обновите страницу</div>;
  } else if (page && project && drawing) {
    main = <SheetStage ref={stage} page={wallPage ?? page} drawing={drawing} project={project.name}
                       onSaved={saved} onBanner={(b) => setBanners([b])} />;
  }
  if (page && project && main) main = <Boundary key={`${current}/${drawn.length > 1 ? "drawing" : loaded}/${reloads}`}>{main}</Boundary>;

  return (
    <div className={css.app}>
      {!current && <Welcome list={list} onOpen={(name) => { location.hash = encodeURIComponent(name); }} />}
      {menu && (
        <ProjectsMenu list={list} current={current} closing={menu === "closing"}
                      onOpen={(name) => { location.hash = encodeURIComponent(name); setMenu("closing"); }}
                      onClose={closeMenu} onClosed={menuClosed} />
      )}
      <header className={css.header}>
        <Logo />
        <button className={css.projectSwitch} aria-expanded={menu === "open"} aria-haspopup="dialog"
                title="Проекты" onClick={() => setMenu(menu === "open" ? "closing" : "open")}>
          <span className={css.arrow} aria-hidden="true">›</span>
          <span className={css.projectName}>
            {list.find((p) => p.name === current)?.title ?? current ?? "Проекты"}
          </span>
        </button>
        <nav className={cx(ui.segmented, css.sheets)} aria-label="Листы">
          {tabs.map((t) => (
            <button key={t.pages[0]} className={cx(t === tab && ui.on)}
                    title={t.pages.length > 1 && !t.views ? `${t.pages.length} страницы` : undefined}
                    onClick={() => openSheet(tabTarget(t))}>{t.name}</button>
          ))}
        </nav>
        <button className={css.more} aria-label="Ещё" aria-expanded={more} onClick={() => setMore(!more)}>⋯</button>
        {/* На телефоне — меню «⋯»: выбрал действие — меню закрылось */}
        <div className={cx(css.actions, more && css.open)} onClick={() => setMore(false)}>
          {project && (
            <div className={ui.segmented} aria-label="Проект">
              {(Object.keys(DRAWER) as DrawerTab[]).map((k) => {
                const n = k === "questions" ? openQs : 0;
                return (
                  <button key={k} className={cx(drawer === k && !closing && ui.on)} aria-pressed={drawer === k && !closing}
                          aria-label={n ? `${DRAWER[k]}: открытых ${n}` : undefined} onClick={() => toggleDrawer(k)}>
                    <span className={css.tabName}>{DRAWER[k]}{n > 0 && <span className={css.count} aria-hidden="true">{n}</span>}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <Settings account={account} theme={theme} onTheme={(t) => { remember("theme", t); setTheme(t); }} />
      </header>
      <div className={css.banners}>
        {outdated && (
          <div className={css.banner}>
            Доступна новая версия Штробы — эта вкладка открыта до обновления и может показывать листы неверно.{" "}
            <button className={css.pill} onClick={() => location.reload()}>Обновить</button>
          </div>
        )}
        {warn && <div className={css.banner}>{warn}</div>}
        {banners.map((b) => <div key={b} className={css.banner}>{b}</div>)}
      </div>
      <main id="stage" className={css.stage}>
        {main}
        {/* Скачать: PNG листа (весь лист, не больше A3 150 dpi) и DXF проекта */}
        {project && current && (
          <DownloadMenu
            onPng={page && !source && !loading ? () => downloadSheetPng(page, `${current}-${page.name}.png`) : null}
            dxf={project.dxf ? { href: `${base(current)}/out/${enc(project.dxf)}`, name: project.dxf } : null} />
        )}
        {loading && (
          <div className={css.loader} role="status" aria-live="polite">
            <span className={css.spinner} aria-hidden="true" />
            <span className="small muted">{project ? "Загружаю лист…" : "Загружаю проект…"}</span>
          </div>
        )}
        {wall && page && !loading ? (
          <>
            {/* Развёртки: одна страница — одна стена; внизу слева — где она в квартире */}
            <div className={css.pager} role="group" aria-label="Развёртки стен">
              <button aria-label="Предыдущая стена" title="PageUp" disabled={wallAt <= 0} onClick={() => turn(-1)}>‹</button>
              <span className={css.pagerTitle}>
                <span className={css.pagerName}>{wall.title}</span><span className="mono muted">{` · ${wallAt + 1} / ${walls.length}`}</span>
              </span>
              <button aria-label="Следующая стена" title="PageDown" disabled={wallAt >= walls.length - 1}
                      onClick={() => turn(1)}>›</button>
            </div>
            {scene && <WallMap scene={scene} elevation={wall.key} title={wall.title} />}
          </>
        ) : tab && !tab.views && tab.pages.length > 1 && page && (
          <div className={css.pager} role="group" aria-label="Страницы листа">
            <button aria-label="Предыдущая страница" title="PageUp" disabled={at <= 0} onClick={() => turn(-1)}>‹</button>
            <span className="mono">{at + 1} / {tab.pages.length}</span>
            <button aria-label="Следующая страница" title="PageDown" disabled={at >= tab.pages.length - 1}
                    onClick={() => turn(1)}>›</button>
          </div>
        )}
      </main>
      <SidePanel tab={side} onTab={showSide} page={source ? null : page} drawing={source ? null : drawing}
                 views={views} view={sheet} onView={openSheet}>
        {drawer && project && (
          <Drawer tab={drawer} project={project} shownSource={source} onSource={showSource}
                  closing={closing} onClose={closeDrawer} onClosed={drawerClosed} />
        )}
      </SidePanel>
    </div>
  );
}
