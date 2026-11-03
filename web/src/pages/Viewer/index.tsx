// Просмотр собранных проектов: проект из адреса (#имя), листы .epd, боковая панель.
// Данные — API просмотра (service/viewer.py); единственная запись — правки проводки.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildDrawing, DRAWING_STAGES } from "@/engine/sheet/drawing";
import { downloadSheetPng } from "@/engine/sheet/paint";
import { wallPages, wallSheet } from "@/engine/sheet/walls";
import { Welcome } from "@/pages/Welcome";
import { base, enc, getManifest, getPage, getProject, listProjects, saveVariant } from "@/shared/api";
import { DRAWER_TABS, SIDE_TABS, type DrawerTab, type SideTab, type Theme } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { label } from "@/shared/i18n";
import { applyTheme, remember, remembered, savedTheme } from "@/shared/palette";
import { resetSelection, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import { sheetTabs, tabOf, VIEWS } from "@/shared/tabs";
import type { ManifestPage, Overview, Page, Project, ProjectSummary, Scene, Variants } from "@/shared/types";
import { watchRebuild } from "@/shared/rebuild";
import { BRAND, watchBuild } from "@/shared/version";
import { Boundary } from "@/ui/Boundary";
import { Logo } from "@/ui/Logo";
import { DownloadMenu } from "@/widgets/DownloadMenu";
import { Drawer } from "@/widgets/Drawer";
import { ElevationStage } from "@/widgets/ElevationStage";
import { EstimateStage, type EstimateItem } from "@/widgets/EstimateStage";
import { OverviewStage, OverviewSummary } from "@/widgets/OverviewStage";
import { RebuildModal } from "@/widgets/RebuildModal";
import { parseKey } from "@/widgets/VariantPicker/variants";
import { PanelStage } from "@/widgets/PanelStage";
import { ProjectsMenu } from "@/widgets/ProjectsMenu";
import { type Account, Settings } from "@/widgets/Settings";
import { SheetStage, type StageHandle } from "@/widgets/SheetStage";
import { SidePanel } from "@/widgets/SidePanel";
import { SourceView } from "@/widgets/SourceView";
import { WallMap } from "@/widgets/WallMap";
import { WallPager } from "@/widgets/WallPager";
import css from "./Viewer.module.scss";

const fromHash = () => decodeURIComponent(location.hash.slice(1)) || null;

// Не разрешённые вопросы: без ответа и с текстовым ответом, который ещё не разобран
const UNRESOLVED = new Set(["open", "text"]);
export const unresolved = (p: Project | null) =>
  (p?.report ? p.report.questions.filter((q) => UNRESOLVED.has(q.state)).length : 0);

// account — кто вошёл (Gate, для настроек); вход выключен — null
export function Viewer({ account = null }: { account?: Account | null }) {
  const { t } = useTranslation();
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
    const saved = remembered("side");
    return (SIDE_TABS as readonly string[]).includes(saved ?? "") ? (saved as SideTab) : "tables";
  });
  const [drawer, setDrawer] = useState<DrawerTab | null>(null);  // вопросы, исходники, проект
  const [closing, setClosing] = useState(false);                // панель уезжает
  const [menu, setMenu] = useState<"open" | "closing" | null>(null);  // меню проектов слева
  const [more, setMore] = useState(false);  // телефон: действия шапки — меню «⋯»
  const [source, setSource] = useState<string | null>(null);  // файл source/, открытый вместо листа
  const [estimate, setEstimate] = useState(false);  // вкладка «Смета» (страница проводки, ключ estimate)
  const [info, setInfo] = useState(false);  // вкладка «Общие сведения» (манифест: overview, variants)
  const [overview, setOverview] = useState<Overview | null>(null);
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const [reloads, setReloads] = useState(0);
  // Пересборка того же проекта: прежние данные остаются на экране под заглушками, пока не придут новые
  const [refreshing, setRefreshing] = useState(false);
  const [shown, setShown] = useState(0);  // reloads, с которыми нарисован чертёж: ключ Boundary меняется вместе с данными
  const reloadsRef = useRef(0);
  reloadsRef.current = reloads;
  const prevProject = useRef<string | null>(null);
  const [variants, setVariants] = useState<Variants | null>(null);  // варианты проводки (манифест)
  const [choosing, setChoosing] = useState(false);  // вариант сохраняется и проект пересобирается
  const [saving, setSaving] = useState(false);  // правки трасс сохраняются и проект пересобирается
  const [outdated, setOutdated] = useState(false);  // после открытия вкладки выложили новую версию
  const stage = useRef<StageHandle>(null);

  // Уйти с листа, где есть несохранённые правки трасс, — только с подтверждения
  const confirmLeave = useCallback(() => {
    const n = stage.current?.pending() ?? 0;
    return !n || confirm(t("app.leave"));
  }, [t]);

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

  // Другой проект — с первой стены; перечитанный тот же — на той же
  useEffect(() => setWallKey(null), [current]);

  // Проект пересобрали, пока вкладка открыта, — перечитать листы (reloads)
  const built = project?.built;
  useEffect(() => {
    if (!current || built === undefined) return;
    return watchRebuild(() => getProject(current).then((p) => p.built), built, () => setReloads((n) => n + 1));
  }, [current, built]);

  // Открытая вкладка проекта (лист или «Смета») — в браузере: после перезагрузки страницы и
  // пересборки — та же. Пишется, только когда проект уже открыт на своём месте (placed)
  const placed = useRef<string | null>(null);
  useEffect(() => {
    if (!current || sheet === null || placed.current !== current) return;
    remember(`place:${current}`, JSON.stringify({ sheet, estimate, info }));
  }, [current, sheet, estimate, info]);

  // Проект: список, отчёт, листы; reloads — перечитать после сохранения правок или пересборки
  useEffect(() => {
    let alive = true;
    const again = !!current && prevProject.current === current && placed.current === current;
    prevProject.current = current;
    if (again) {
      setRefreshing(true);  // тот же проект: ничего не сбрасываем, чтобы блоки не пропадали
    } else {
      placed.current = null;
      setProject(null); setPages([]); setPage(null); setLoaded(null); setDrawn([]); setElevs([]); setScene(null);
      setError(null); setSource(null); setEstimate(false); setInfo(false); setOverview(null);
      setRefreshing(false); setShown(reloadsRef.current);
    }
    cache.current = new Map();
    listProjects().then((l) => alive && setList(l)).catch(() => {});
    if (!current) return;
    (async () => {
      try {
        const p = await getProject(current);
        if (!alive) return;
        setProject(p);
        if (!p.artifact) { setRefreshing(false); return; }
        const m = await getManifest(current);
        if (!alive) return;
        // Ведомость точек — для печати; в просмотре она в боковой панели листа электрики
        const shown = m.pages.filter((pg) => pg.stage !== "points");
        setPages(shown);
        setVariants(m.variants ?? null);
        setOverview(m.overview ?? null);
        const saved = savedPlace(current);
        const has = (i: unknown) => shown.some((pg) => pg.index === i);
        setSheet((s) => (has(saved?.sheet) ? saved!.sheet : has(s) ? s : shown[0]?.index ?? null));
        setEstimate(!!saved?.estimate && shown.some((pg) => (pg.stage === "wiring" || pg.stage === "plumbing") && pg.index === saved.sheet));
        // Первый заход в проект — «Общие сведения»; дальше — где был
        setInfo(saved === null || saved.info);
        placed.current = current;
      } catch (e) {
        if (alive) { setError((e as Error).message); setRefreshing(false); }
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
  // Смета сантехники — на странице «Сантехника»; без проводки вкладка «Смета» открывает её
  const estimateSheet = sceneSheet ?? pages.find((pg) => pg.stage === "plumbing")?.index;

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
      setShown(reloadsRef.current); setRefreshing(false);
      // Те же страницы — тот же чертёж: холст, масштаб и сдвиг остаются
      const own = walls ? [pgs[want.indexOf(sheet)]] : pgs;
      setDrawn((prev) => (prev.length === own.length && prev.every((p, i) => p === own[i]) ? prev : own));
    }, (e) => alive && (setError((e as Error).message), setRefreshing(false)));
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
    setEstimate(false); setInfo(false);
    if (source) { setSource(null); resetSelection(); setSheet(index); return; }
    if (page && index === sheet) {  // лист уже открыт: правки не терять, из 3D — на лист
      if (view.get().show3d) view.set({ show3d: false, pinned: null, selected: null, neighbors: null, tip: null });
      return;
    }
    const sameDrawing = sheet !== null && drawingSheets.includes(sheet) && drawingSheets.includes(index);
    if (confirmLeave()) { resetSelection(sameDrawing); setSheet(index); }
  };
  // С развёртки — на лист проводки, сразу к линии точки или коробки (store.goto)
  const toWiring = sceneSheet === undefined ? undefined : (key: string) => {
    view.set({ goto: key });
    openSheet(sceneSheet);
  };
  // «Смета» — не лист: страница проводки (там ключ estimate) без чертежа; смета сантехники —
  // со страницы «Сантехника», она того же чертежа и уже загружена (drawn)
  const openEstimate = estimateSheet === undefined ? undefined : () => {
    openSheet(estimateSheet);
    setEstimate(true);
  };
  // «Общие сведения» — не лист: страница из манифеста; лист под ней остаётся загруженным
  const openInfo = () => {
    if (!confirmLeave()) return;
    setSource(null); setEstimate(false); setInfo(true);
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
    setRefreshing(true);
    setReloads((n) => n + 1);
    setSaving(false);
  };

  // Другой вариант проводки: несохранённые правки трасс — только с подтверждения
  const chooseVariant = (v: { mode: string; route: string; distribution: string }, ceiling?: number) => {
    if (!current || !confirmLeave()) return;
    setChoosing(true);
    saveVariant(current, ceiling === undefined ? v : { ...v, ceiling_height: ceiling })
      .then(() => saved([]))
      .catch((e: Error) => setBanners([t("variant.failed", { message: e.message })]))
      .finally(() => setChoosing(false));
  };

  // Продолжения (развёртки) — одна вкладка, страницы — внутри чертежа; электрика, освещение
  // и проводка — одна вкладка, вид — переключателем справа (SidePanel)
  const tabs = sheetTabs(pages);
  const tab = source || estimate || info ? null : tabOf(tabs, sheet);
  const stageOf = (i: number) => pages.find((pg) => pg.index === i)?.stage ?? "";
  const views = tab?.views ? tab.pages.map((i) => ({ index: i, label: label("views", stageOf(i)) })) : null;
  // Вкладка с видами открывается на последнем выбранном виде
  const [lastView, setLastView] = useState(() => remembered("view") || "electrical");
  useEffect(() => {
    const st = pages.find((pg) => pg.index === sheet)?.stage;
    if (st && VIEWS.has(st)) { setLastView(st); remember("view", st); }
  }, [sheet, pages]);
  const tabTarget = (tb: (typeof tabs)[number]) =>
    (tb === tab && sheet !== null ? sheet : tb.views ? tb.pages.find((i) => stageOf(i) === lastView) ?? tb.pages[0] : tb.pages[0]);
  const at = tab && sheet !== null ? tab.pages.indexOf(sheet) : -1;
  // Страницы вкладки развёрток — стены, а не листы
  const wallAt = wall ? walls.indexOf(wall) : -1;
  const openWall = (index: number) => {
    const next = walls[index];
    if (!next) return;
    setWallKey(next.key);
    if (next.sheet !== sheet) openSheet(next.sheet);
    else resetSelection();
  };
  const turn = (step: number) => {
    if (wallAt >= 0) { openWall(wallAt + step); return; }
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
  // Вариант проводки строкой в боковой панели листов: «Стандарт · По потолку · Через коробки»
  const activeVariant = variants ? parseKey(variants.active) : null;
  const variantLabel = activeVariant
    ? [t(`variant.modes.${activeVariant.mode}`), t(`variant.routes.${activeVariant.route}`), t("variant.distributions.boxes")].join(" · ")
    : null;
  const warn = project?.stale
    ? t("app.stale", { name: project.name })
    : project && !project.report ? t("app.notBuilt", { name: project.name }) : null;

  // Пока грузится проект или лист — прелоадер поверх чертежа (прежний лист виден под ним)
  const loading = !!current && !error && !source && (!project || (!!project.artifact && loaded !== sheet));

  let main: React.ReactNode;
  if (!current) main = <div className={ui.empty}>{t("app.chooseProject")}</div>;
  else if (error) main = <div className={ui.error}>{error}</div>;
  else if (source && project) main = <SourceView project={project} file={source} onBack={() => setSource(null)} />;
  else if (project && !project.artifact) main = <div className={ui.empty}>{t("app.noArtifact")}</div>;
  else if (info && project) {
    main = <OverviewStage overview={overview} variants={variants} project={project} openQuestions={openQs}
                          canChoose={project.can?.choose_variant ?? true} busy={choosing} refreshing={refreshing || choosing} onChoose={chooseVariant}
                          onEstimate={openEstimate} onDrawer={(k) => { setDrawer(k); setClosing(false); }} />;
  }
  else if (estimate && page && project) {
    const xlsx = (f: string) => (project.files.includes(f) ? `${base(current)}/out/${f}` : null);
    const items: EstimateItem[] = [];
    const wiring = [page, ...drawn].find((p) => p.stage === "wiring" && p.estimate);
    const water = [page, ...drawn].find((p) => p.stage === "plumbing" && p.estimate);
    if (wiring?.estimate) items.push({ table: wiring.estimate, xlsx: xlsx("estimate.xlsx") });
    if (water?.estimate) items.push({ table: water.estimate, xlsx: xlsx("plumbing-estimate.xlsx") });
    main = items.length ? <EstimateStage items={items} /> : <div className={ui.empty}>{t("estimate.none")}</div>;
  }
  else if (page && project && page.panel) {
    main = <PanelStage ref={stage} page={page} panel={page.panel} language={overview?.language} />;
  } else if (page && project && !page.items?.length) {
    main = <div className={ui.error}>{t("app.nothingToDraw", { name: page.name })}</div>;
  } else if (page && project && wall?.data && elevSheets.includes(loaded ?? -1)) {
    main = <ElevationStage ref={stage} elevation={wall.data} withMap={!!scene} />;
  } else if (page && project && drawing) {
    main = <SheetStage ref={stage} page={wallPage ?? page} drawing={drawing} project={project.name}
                       editable={project.can?.edit_wiring ?? true}
                       onSaved={saved} onBusy={setSaving} onBanner={(b) => setBanners([b])} />;
  }
  if (page && project && main) main = <Boundary key={`${current}/${drawn.length > 1 ? "drawing" : loaded}/${shown}`}>{main}</Boundary>;

  return (
    <div className={css.app}>
      {(choosing || saving) && <RebuildModal />}
      {!current && <Welcome list={list} onOpen={(name) => { location.hash = encodeURIComponent(name); }} />}
      {menu && (
        <ProjectsMenu list={list} current={current} closing={menu === "closing"}
                      onOpen={(name) => { location.hash = encodeURIComponent(name); setMenu("closing"); }}
                      onClose={closeMenu} onClosed={menuClosed} />
      )}
      <header className={css.header}>
        <Logo />
        <button className={css.projectSwitch} aria-expanded={menu === "open"} aria-haspopup="dialog"
                title={t("app.projects")} onClick={() => setMenu(menu === "open" ? "closing" : "open")}>
          <span className={css.arrow} aria-hidden="true">›</span>
          <span className={css.projectName}>
            {list.find((p) => p.name === current)?.title ?? current ?? t("app.projects")}
          </span>
        </button>
        <nav className={cx(ui.segmented, css.sheets)} aria-label={t("app.sheets")}>
          {/* Вкладка есть у любого собранного проекта: сборка без сведений (старый код) — с подсказкой пересобрать */}
          {project?.artifact && pages.length > 0 && (
            <button className={cx(info && ui.on)} onClick={openInfo}>{t("overview.tab")}</button>
          )}
          {tabs.map((tb) => (
            <button key={tb.pages[0]} className={cx(tb === tab && ui.on)}
                    title={tb.pages.length > 1 && !tb.views ? t("app.pages", { n: tb.pages.length }) : undefined}
                    onClick={() => openSheet(tabTarget(tb))}>{tb.stage ? label("stage", tb.stage) : tb.name}</button>
          ))}
          {openEstimate && (
            <button className={cx(estimate && ui.on)} onClick={openEstimate}>{t("estimate.tab")}</button>
          )}
        </nav>
        <button className={css.more} aria-label={t("app.more")} aria-expanded={more} onClick={() => setMore(!more)}>⋯</button>
        {/* На телефоне — меню «⋯»: выбрал действие — меню закрылось */}
        <div className={cx(css.actions, more && css.open)} onClick={() => setMore(false)}>
          {project && (
            <div className={ui.segmented} aria-label={t("app.project")}>
              {DRAWER_TABS.map((k) => {
                const n = k === "questions" ? openQs : 0;
                return (
                  <button key={k} className={cx(drawer === k && !closing && ui.on)} aria-pressed={drawer === k && !closing}
                          aria-label={n ? t("app.openCount", { name: t(`drawer.${k}`), n }) : undefined} onClick={() => toggleDrawer(k)}>
                    <span className={css.tabName}>{t(`drawer.${k}`)}{n > 0 && <span className={css.count} aria-hidden="true">{n}</span>}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <Settings account={account} theme={theme} onTheme={(th) => { remember("theme", th); setTheme(th); }} />
      </header>
      <div className={css.banners}>
        {outdated && (
          <div className={css.banner}>
            {t("app.newVersion", { brand: BRAND })}{" "}
            <button className={css.pill} onClick={() => location.reload()}>{t("common.refresh")}</button>
          </div>
        )}
        {warn && <div className={css.banner}>{warn}</div>}
        {banners.map((b) => <div key={b} className={css.banner}>{b}</div>)}
      </div>
      <main id="stage" className={css.stage}>
        {main}
        {/* Скачать: PNG листа (весь лист, не больше A3 150 dpi) и DXF проекта */}
        {project && current && !estimate && !info && (
          <DownloadMenu
            onPng={page && !source && !estimate && !loading ? () => downloadSheetPng(page, `${current}-${page.name}.png`) : null}
            dxf={project.dxf ? { href: `${base(current)}/out/${enc(project.dxf)}`, name: project.dxf } : null} />
        )}
        {loading && !info && (
          <div className={css.loader} role="status" aria-live="polite">
            <span className={css.spinner} aria-hidden="true" />
            <span className="small muted">{project ? t("app.loadingSheet") : t("app.loadingProject")}</span>
          </div>
        )}
        {wall && page && !loading && !info && !estimate && !source ? (
          <>
            {/* Развёртки: одна страница — одна стена, имя — список всех стен; внизу слева — где она в квартире */}
            <WallPager walls={walls} at={wallAt} onTurn={turn} onPick={openWall} />
            {scene && <WallMap scene={scene} elevation={wall.key} title={wall.title} face={wall.data?.face} />}
          </>
        ) : tab && !tab.views && tab.pages.length > 1 && page && (
          <div className={css.pager} role="group" aria-label={t("app.sheetPages")}>
            <button aria-label={t("app.prevPage")} title="PageUp" disabled={at <= 0} onClick={() => turn(-1)}>‹</button>
            <span className="mono">{at + 1} / {tab.pages.length}</span>
            <button aria-label={t("app.nextPage")} title="PageDown" disabled={at >= tab.pages.length - 1}
                    onClick={() => turn(1)}>›</button>
          </div>
        )}
      </main>
      <SidePanel tab={side} onTab={showSide} page={source ? null : page} drawing={source ? null : drawing}
                 estimate={estimate && !source ? page?.estimate ?? null : null}
                 views={views} view={sheet} onView={openSheet}
                 wall={!source && !loading ? wall?.data ?? null : null} onWiring={toWiring}
                 variant={variantLabel ? { label: variantLabel, onOpen: openInfo } : null}
                 summary={info && !source ? <OverviewSummary variants={variants} plumbing={overview?.plumbing?.estimate} openQuestions={openQs} refreshing={refreshing || choosing} /> : undefined}>
        {drawer && project && (
          <Drawer tab={drawer} project={project} shownSource={source} onSource={showSource}
                  closing={closing} onClose={closeDrawer} onClosed={drawerClosed} />
        )}
      </SidePanel>
    </div>
  );
}

// Где был открыт проект в этом браузере: лист, вкладка «Смета» или «Общие сведения» (place:<проект>)
function savedPlace(name: string): { sheet: number; estimate: boolean; info: boolean } | null {
  try {
    const v = JSON.parse(remembered(`place:${name}`) || "null") as { sheet?: unknown; estimate?: unknown; info?: unknown } | null;
    return v && typeof v.sheet === "number" ? { sheet: v.sheet, estimate: v.estimate === true, info: v.info === true } : null;
  } catch {
    return null;
  }
}
