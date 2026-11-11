// Viewer of built projects: the project from the address (#name), .epd sheets, side panel.
// Data comes from the viewer API (service/viewer.py); the only write is wiring edits.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildDrawing, DRAWING_STAGES } from "@/engine/sheet/drawing";
import { downloadSheetPng } from "@/engine/sheet/paint";
import { wallPages, wallSheet } from "@/engine/sheet/walls";
import { STUDIO_SECTIONS, Studio, type StudioSection } from "@/pages/Studio";
import { Welcome } from "@/pages/Welcome";
import { base, enc, getManifest, getPage, getProject, isProject, listProjects, reviewAnswer, saveAnswer, saveWizard, type ReviewOutcome, type WizardBody } from "@/shared/api";
import { NARROW_PX, SIDE_TABS, stickersPdf, type DrawerTab, type PanelMode, type SideTab, type Theme } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { label } from "@/shared/i18n";
import { modeDrawerTabs, modeTabs, rememberMode, savedMode, stageShown, type UiMode } from "@/shared/mode";
import { applyTheme, remember, remembered, savedTheme } from "@/shared/palette";
import { hideSplash } from "@/shared/splash";
import { useUnderline } from "@/shared/underline";
import { resetSelection, useView, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import { sheetTabs, tabOf, VIEWS, type TabView } from "@/shared/tabs";
import type { ManifestPage, Overview, Page, Project, ProjectSummary, Scene, Variants } from "@/shared/types";
import { RESERVE_KEY, type Answer, type QuestionsMemory } from "@/shared/questions";
import { watchRebuild } from "@/shared/rebuild";
import { BRAND, watchBuild } from "@/shared/version";
import { Boundary } from "@/ui/Boundary";
import { Logo } from "@/ui/Logo";
import { MarkLoader } from "@/ui/MarkLoader";
import { AlphaNotice } from "@/widgets/AlphaNotice";
import { DownloadMenu } from "@/widgets/DownloadMenu";
import { Drawer } from "@/widgets/Drawer";
import { ElevationStage } from "@/widgets/ElevationStage";
import { EstimateStage, type EstimateItem } from "@/widgets/EstimateStage";
import { OverviewStage, OverviewSummary } from "@/widgets/OverviewStage";
import { RebuildModal } from "@/widgets/RebuildModal";
import { activeSummary, breakersOf, parseKey } from "@/widgets/VariantInfo/variants";
import { PanelStage } from "@/widgets/PanelStage";
import { ProjectsMenu } from "@/widgets/ProjectsMenu";
import { type Account, Settings } from "@/widgets/Settings";
import { SheetStage, type StageHandle } from "@/widgets/SheetStage";
import { SidePanel } from "@/widgets/SidePanel";
import { SourceView } from "@/widgets/SourceView";
import { WallMap } from "@/widgets/WallMap";
import { WallGrid } from "@/widgets/WallGrid";
import { useCurtain } from "@/shared/curtain";
import { WallPager } from "@/widgets/WallPager";
import { Wizard } from "@/widgets/Wizard";
import { setupOf, setupProgress, type StepId } from "@/widgets/Wizard/steps";
import css from "./Viewer.module.scss";

// #<project> — a project; #@studio[/<section>] — the studio settings (project names never start
// with @); the old #@prices — its price list
const hashValue = () => decodeURIComponent(location.hash.slice(1));
const fromHash = () => (hashValue().startsWith("@") ? null : hashValue() || null);
function studioFromHash(): StudioSection | null {
  const v = hashValue();
  if (v === "@prices") return "prices";
  if (v !== "@studio" && !v.startsWith("@studio/")) return null;
  const s = v.slice("@studio/".length) as StudioSection;
  return STUDIO_SECTIONS.includes(s) ? s : "profile";
}
const studioHash = (s: StudioSection) => (s === "profile" ? "@studio" : `@studio/${s}`);

// Unresolved questions: without an answer, or with a text answer not handled yet
const UNRESOLVED = new Set(["open", "text"]);
export const unresolved = (p: Project | null) =>
  (p?.report ? p.report.questions.filter((q) => UNRESOLVED.has(q.state)).length : 0);

// account is who is logged in (Gate, for settings); null if login is off
const QUESTION_AROUND = 0.4;  // a question's object is seen in its room, not alone at the largest zoom

export function Viewer({ account = null }: { account?: Account | null }) {
  const { t } = useTranslation();
  const [list, setList] = useState<ProjectSummary[]>([]);
  const [current, setCurrent] = useState<string | null>(fromHash);
  const [studio, setStudio] = useState(studioFromHash);  // the open studio settings section
  const outside = useRef(studioFromHash() ? "" : location.hash.slice(1));  // where the settings were opened from
  const [project, setProject] = useState<Project | null>(null);
  const [pages, setPages] = useState<ManifestPage[]>([]);
  const [sheet, setSheet] = useState<number | null>(null);
  const [page, setPage] = useState<Page | null>(null);
  const [loaded, setLoaded] = useState<number | null>(null);  // the sheet whose page is currently in page
  const [drawn, setDrawn] = useState<Page[]>([]);  // sheets of the drawing page belongs to
  const [elevs, setElevs] = useState<{ index: number; page: Page }[]>([]);  // elevation sheets
  const [scene, setScene] = useState<Scene | null>(null);  // 3D scene, for the elevation mini map
  const [wallKey, setWallKey] = useState<string | null>(null);  // the open elevation
  const cache = useRef(new Map<number, Promise<Page>>());  // project pages, once
  const [error, setError] = useState<string | null>(null);
  const [banners, setBanners] = useState<string[]>([]);
  const [side, setSide] = useState<SideTab>(() => {
    const saved = remembered("side");
    return (SIDE_TABS as readonly string[]).includes(saved ?? "") ? (saved as SideTab) : "tables";
  });
  const [drawer, setDrawer] = useState<DrawerTab | null>(null);  // questions, sources, project
  const [closing, setClosing] = useState(false);                // the panel slides away
  const [menu, setMenu] = useState<"open" | "closing" | null>(null);  // project menu on the left
  const [more, setMore] = useState(false);  // phone: header actions in the "⋯" menu
  const [source, setSource] = useState<string | null>(null);  // a source/ file opened instead of a sheet
  const [estimate, setEstimate] = useState(false);  // "Estimate" tab (wiring page, key estimate)
  const [info, setInfo] = useState(false);  // "Overview" tab (manifest: overview, variants)
  const [overview, setOverview] = useState<Overview | null>(null);
  const [theme, setTheme] = useState<Theme>(savedTheme);
  const [mode, setMode] = useState<UiMode>(() => savedMode(account));  // simple or engineering interface (shared/mode.ts)
  const [reloads, setReloads] = useState(0);
  // Rebuilding the same project: the previous data stays on screen under placeholders until the new data arrives
  const [refreshing, setRefreshing] = useState(false);
  const [shown, setShown] = useState(0);  // the reloads the drawing was drawn with: the Boundary key changes with the data
  const reloadsRef = useRef(0);
  reloadsRef.current = reloads;
  const prevProject = useRef<string | null>(null);
  const [variants, setVariants] = useState<Variants | null>(null);  // wiring variants (manifest)
  const [choosing, setChoosing] = useState(false);  // the variant is being saved and the project rebuilt
  const [wizard, setWizard] = useState(false);  // the setup wizard is open
  const [wizardStart, setWizardStart] = useState<StepId | undefined>();  // the step it opens on
  const [panelMode, setPanelMode] = useState<PanelMode>("front");  // what the "Panel" page shows
  const questionsMemory = useRef<QuestionsMemory>({ drafts: {} });
  const [answering, setAnswering] = useState(false);  // an answer from a question card is being saved
  const [saving, setSaving] = useState(false);  // route edits are being saved and the project rebuilt
  const [outdated, setOutdated] = useState(false);  // a new version was deployed after the tab was opened
  const stage = useRef<StageHandle>(null);

  // Leaving a sheet with unsaved route edits only after confirmation
  const confirmLeave = useCallback(() => {
    const n = stage.current?.pending() ?? 0;
    return !n || confirm(t("app.leave"));
  }, [t]);

  useEffect(() => {
    const onHash = () => {
      if (!confirmLeave()) {  // stay on the sheet with unsaved edits
        history.replaceState(null, "", `#${encodeURIComponent(current || "")}`);
        return;
      }
      setCurrent(fromHash());
      setStudio(studioFromHash());
      if (!studioFromHash()) outside.current = location.hash.slice(1);
    };
    const onUnload = (ev: BeforeUnloadEvent) => { if (stage.current?.pending()) ev.preventDefault(); };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("beforeunload", onUnload);
    return () => { window.removeEventListener("hashchange", onHash); window.removeEventListener("beforeunload", onUnload); };
  }, [current, confirmLeave]);

  useEffect(() => watchBuild(() => setOutdated(true)), []);

  // Theme: system → light → dark; canvas and 3D are recoloured
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

  // Another project starts at the first wall; the same project reloaded stays on the same wall
  useEffect(() => setWallKey(null), [current]);

  // The project was rebuilt while the tab is open: reload the sheets (reloads)
  const built = project?.built;
  useEffect(() => {
    if (!current || built === undefined) return;
    return watchRebuild(() => getProject(current).then((p) => p.built), built, () => setReloads((n) => n + 1));
  }, [current, built]);

  // The open project tab (a sheet or "Estimate") is kept in the browser, so after a page reload
  // or a rebuild it is the same. It is written only once the project is open in its place (placed)
  const placed = useRef<string | null>(null);
  useEffect(() => {
    if (!current || sheet === null || placed.current !== current) return;
    remember(`place:${current}`, JSON.stringify({ sheet, estimate, info }));
  }, [current, sheet, estimate, info]);

  // Project: list, report, sheets; reloads re-reads after saving edits or a rebuild
  useEffect(() => {
    let alive = true;
    const again = !!current && prevProject.current === current && placed.current === current;
    prevProject.current = current;
    if (again) {
      setRefreshing(true);  // the same project: reset nothing so blocks do not disappear
      setError(null);       // only an old failure, for example sheets read in the middle of a rebuild
    } else {
      placed.current = null;
      setProject(null); setPages([]); setPage(null); setLoaded(null); setDrawn([]); setElevs([]); setScene(null);
      setError(null); setSource(null); setEstimate(false); setInfo(false); setOverview(null);
      setRefreshing(false); setShown(reloadsRef.current); setWizard(false); setPanelMode("front");
      questionsMemory.current = { drafts: {} };
    }
    cache.current = new Map();
    listProjects().then((l) => alive && setList(l)).catch(() => {}).finally(hideSplash);
    if (!current) return;
    (async () => {
      try {
        const p = await getProject(current);
        if (!alive) return;
        setProject(p);
        if (!p.artifact) { setRefreshing(false); return; }
        const m = await getManifest(current);
        if (!alive) return;
        // The point schedule is for print; in the viewer it is in the side panel of the electrical sheet
        const shown = m.pages.filter((pg) => pg.stage !== "points");
        setPages(shown);
        setVariants(m.variants ?? null);
        setOverview(m.overview ?? null);
        const saved = savedPlace(current);
        const has = (i: unknown) => shown.some((pg) => pg.index === i);
        setSheet((s) => (has(saved?.sheet) ? saved!.sheet : has(s) ? s : shown[0]?.index ?? null));
        setEstimate(!!saved?.estimate && shown.some((pg) => (pg.stage === "wiring" || pg.stage === "plumbing") && pg.index === saved.sheet));
        // The first visit to a project opens "Overview"; after that, where you were
        setInfo(saved === null || saved.info);
        placed.current = current;
      } catch (e) {
        if (alive) { setError((e as Error).message); setRefreshing(false); }
      }
    })();
    return () => { alive = false; };
  }, [current, reloads]);

  // Sheets with a plan (plan, electrical, lighting, wiring) are one drawing: they load together,
  // and a tab between them is a different set of layers of the same drawing (sheet/drawing.ts)
  const drawingSheets = useMemo(
    () => pages.filter((pg) => pg.stage && DRAWING_STAGES.has(pg.stage)).map((pg) => pg.index), [pages]);
  // Elevations go wall by wall: the tab's sheets load together, and with them the sheet with the scene
  const elevSheets = useMemo(() => pages.filter((pg) => pg.stage === "elevations").map((pg) => pg.index), [pages]);
  const sceneSheet = pages.find((pg) => pg.stage === "wiring")?.index;
  // The plumbing estimate is on the "Plumbing" page; without wiring the "Estimate" tab opens it
  const estimateSheet = sceneSheet ?? pages.find((pg) => pg.stage === "plumbing")?.index;

  // The setup wizard shows the flat in 3D on the ceiling step: the scene loads when it opens
  useEffect(() => {
    if (!wizard || scene || !current || sceneSheet === undefined) return;
    let alive = true;
    let p = cache.current.get(sceneSheet);
    if (!p) {
      p = getPage(current, sceneSheet);
      cache.current.set(sceneSheet, p);
      p.catch(() => cache.current.delete(sceneSheet));
    }
    p.then((pg) => alive && setScene(pg.scene ?? null), () => {});
    return () => { alive = false; };
  }, [wizard, scene, current, sceneSheet]);

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
    // The mini map scene is optional: if it fails to load, elevations go without the map
    if (walls && sceneSheet !== undefined) {
      load(sceneSheet).then((pg) => alive && setScene(pg.scene ?? null), () => {});
    }
    Promise.all(want.map(load)).then((pgs) => {
      if (!alive) return;
      if (walls) setElevs(want.map((index, i) => ({ index, page: pgs[i] })));
      // A tab of the same drawing keeps 3D (only layers change); another sheet starts with the plan
      const was = drawnRef.current;
      resetSelection(pgs.length > 1 && was.length === pgs.length && was.every((p, i) => p === pgs[i]));
      setPage(pgs[want.indexOf(sheet)]);
      setLoaded(sheet);
      setShown(reloadsRef.current); setRefreshing(false);
      // The same pages mean the same drawing: canvas, zoom and pan stay
      const own = walls ? [pgs[want.indexOf(sheet)]] : pgs;
      setDrawn((prev) => (prev.length === own.length && prev.every((p, i) => p === own[i]) ? prev : own));
    }, (e) => alive && (setError((e as Error).message), setRefreshing(false)));
    return () => { alive = false; };
  }, [current, sheet, pages, drawingSheets, elevSheets, sceneSheet]);

  const sheetDrawing = useMemo(() => (drawn.length ? buildDrawing(drawn) : null), [drawn]);
  // Wall elevation: the same sheet, the viewport is its bounding box
  const walls = useMemo(() => wallPages(elevs), [elevs]);
  const wall = walls.find((w) => w.key === wallKey && w.sheet === sheet) ?? walls.find((w) => w.sheet === sheet) ?? null;
  const wallPage = useMemo(() => (wall && page && elevSheets.includes(loaded ?? -1) ? wallSheet(page, wall) : null),
    [wall, page, elevSheets, loaded]);
  const wallDrawing = useMemo(() => (wallPage ? buildDrawing([wallPage]) : null), [wallPage]);
  const drawing = wallDrawing ?? sheetDrawing;
  const drawnRef = useRef(drawn);
  drawnRef.current = drawn;

  // Another sheet: drop the hint, 3D and edits right away, without waiting for the page to load
  const openSheet = (index: number): boolean => {
    setEstimate(false); setInfo(false);
    if (source) { setSource(null); resetSelection(); setSheet(index); return true; }
    if (page && index === sheet) {  // the sheet is already open: keep the edits, leave 3D for the sheet
      if (view.get().show3d) view.set({ show3d: false, pinned: null, selected: null, neighbors: null, tip: null });
      return true;
    }
    const sameDrawing = sheet !== null && drawingSheets.includes(sheet) && drawingSheets.includes(index);
    if (!confirmLeave()) return false;
    resetSelection(sameDrawing);
    setSheet(index);
    return true;
  };
  // From an elevation to the wiring sheet, straight to the line of a point or box (store.goto)
  const toWiring = sceneSheet === undefined ? undefined : (key: string) => {
    if (openSheet(sceneSheet)) view.set({ goto: { key, stage: "wiring" } });
  };
  // From a question to its object, or to the "Panel" tab; on a narrow screen the panel covers
  // the drawing, so it closes (what was typed stays in questionsMemory)
  // An object of the electrical sheet that lives on another view now (SheetStage, goto)
  const openStage = (stage: string) => {
    const index = pages.find((pg) => pg.stage === stage)?.index;
    if (index !== undefined) openSheet(index);
  };
  const showQuestion = ({ stage, key }: { stage: string; key: string | null }) => {
    const index = pages.find((pg) => pg.stage === stage)?.index;
    if (index === undefined || !openSheet(index)) return;
    if (key === RESERVE_KEY) setPanelMode("reserve");
    else if (key) view.set({ goto: { key, stage, around: QUESTION_AROUND } });
    if (window.innerWidth <= NARROW_PX) closeDrawer();
  };
  // "Estimate" is not a sheet: it is the wiring page (which has the estimate key) without the
  // drawing; the plumbing estimate comes from the "Plumbing" page, which is part of the same
  // drawing and already loaded (drawn)
  const openEstimate = estimateSheet === undefined ? undefined : () => {
    openSheet(estimateSheet);
    setEstimate(true);
  };
  // "Overview" is not a sheet: a page from the manifest; the sheet under it stays loaded
  const openInfo = () => {
    if (!confirmLeave()) return;
    setSource(null); setEstimate(false); setInfo(true);
  };
  const showSide = (tab: SideTab) => { setSide(tab); remember("side", tab); };
  // The same button closes (the panel slides away), another one opens its panel
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

  // An answer from the question card: no modal, the panel stays usable during the rebuild.
  // A text answer changes no sheet, so only the project is read again
  const answerQuestion = async (id: string, answer: Answer | null) => {
    if (!current || !confirmLeave()) return null;
    setAnswering(true);
    try {
      const result = await saveAnswer(current, id, answer);
      if (result.rebuilt) saved([]);
      else setProject(await getProject(current));
      return result;
    } finally {
      setAnswering(false);
    }
  };

  // The studio reviews a client answer: taken into account rebuilds, sent back only saves
  const reviewQuestion = async (id: string, outcome: ReviewOutcome, comment?: string) => {
    if (!current || !confirmLeave()) return null;
    setAnswering(true);
    try {
      const result = await reviewAnswer(current, id, outcome, comment);
      if (result.rebuilt) saved([]);
      else setProject(await getProject(current));
      return result;
    } finally {
      setAnswering(false);
    }
  };

  // The setup wizard: all choices at once, one rebuild; a refusal stays in the wizard
  const applyWizard = async (body: WizardBody) => {
    if (!current || !confirmLeave()) return false;
    setChoosing(true);
    try {
      const result = await saveWizard(current, body);
      if (result.rebuilt) saved([]);
      else setProject(await getProject(current));
      setWizard(false);
      return true;
    } finally {
      setChoosing(false);
    }
  };
  const openWizard = (step?: StepId) => { setWizardStart(step); setWizard(true); };
  const setup = useMemo(() => {
    if (!project) return null;
    return setupProgress(setupOf(project, variants, overview?.ceiling.height ?? null, overview?.panel?.reserve ?? null,
                                 overview?.panel?.master ?? null));
  }, [project, variants, overview]);

  // Continuations (elevations) are one tab with pages inside the drawing; electrical, lighting
  // and wiring are one tab, the view is picked with the switch on the right (SidePanel)
  // The simple mode drops the engineering sheets from the tabs (shared/mode.ts)
  const tabs = modeTabs(sheetTabs(pages), (i) => pages.find((pg) => pg.index === i)?.stage, mode);
  const electricalView = useView((s) => s.electricalView);
  const tab = source || estimate || info ? null : tabOf(tabs, sheet);
  const stageOf = (i: number) => pages.find((pg) => pg.index === i)?.stage ?? "";
  // The electrical sheet gives two views: sockets and, if the project has it, low voltage
  const hasLow = !!sheetDrawing?.items.some((it) => it.l === "E-DATA" || it.l.startsWith("W-CABLE-LOW"));
  const views: TabView[] | null = tab?.views ? tab.pages.flatMap((i) => {
    const key = stageOf(i), one = { key, index: i, label: label("views", key) };
    return key === "electrical" && hasLow ? [one, { key: "low", index: i, label: label("views", "low") }] : [one];
  }) : null;
  const pickView = (v: TabView) => {
    view.set({ electricalView: v.key === "low" ? "low" : "sockets", selected: null, neighbors: null, pinned: null, tip: null });
    openSheet(v.index);
  };
  const shownView = stageOf(sheet ?? -1) === "electrical" && electricalView === "low" ? "low" : stageOf(sheet ?? -1);
  // A tab with views opens on the last chosen view
  const [lastView, setLastView] = useState(() => remembered("view") || "electrical");
  useEffect(() => {
    const st = pages.find((pg) => pg.index === sheet)?.stage;
    if (st && VIEWS.has(st)) { setLastView(st); remember("view", st); }
  }, [sheet, pages]);
  const tabTarget = (tb: (typeof tabs)[number]) =>
    (tb === tab && sheet !== null ? sheet : tb.views ? tb.pages.find((i) => stageOf(i) === lastView) ?? tb.pages[0] : tb.pages[0]);
  const at = tab && sheet !== null ? tab.pages.indexOf(sheet) : -1;
  // The simple mode was switched on over a sheet it hides (wiring, panel): to the first tab it shows
  const hidden = !source && !estimate && !info && sheet !== null && !stageShown(mode, stageOf(sheet));
  useEffect(() => {
    if (hidden && tabs[0]) openSheet(tabTarget(tabs[0]));
  }, [hidden]);
  const drawerTabs = modeDrawerTabs(mode);
  useEffect(() => { view.set({ cables: mode === "engineering" }); }, [mode]);
  useEffect(() => {  // a header panel the mode hides closes
    if (drawer && !modeDrawerTabs(mode).includes(drawer)) drawerClosed();
  }, [drawer, mode, drawerClosed]);
  // Pages of the elevations tab are walls, not sheets
  const wallAt = wall ? walls.indexOf(wall) : -1;
  // The "All walls" overview over the elevation: the elevations tab opens on it (a wall is picked
  // there); a jump to one wall (a hint, the pager) goes straight to it
  const [allWalls, setAllWalls] = useState(false);
  const closeAllWalls = useCallback(() => setAllWalls(false), []);
  const onWalls = sheet !== null && elevSheets.includes(sheet) && !info && !estimate && !source;
  useEffect(() => { if (!onWalls) setAllWalls(false); }, [onWalls]);
  const openWall = (index: number) => {
    const next = walls[index];
    if (!next) return;
    setWallKey(next.key);
    if (next.sheet !== sheet) openSheet(next.sheet);
    else resetSelection();
  };
  // From a hint to a wall elevation. Elevation pages load on the way, so the wall's own sheet is
  // known only then: the effect below moves there
  const toWall = elevSheets.length ? (key: string) => { if (openSheet(elevSheets[0])) setWallKey(key); } : undefined;
  useEffect(() => {
    const target = walls.find((w) => w.key === wallKey);
    if (target && elevSheets.includes(sheet ?? -1) && target.sheet !== sheet) setSheet(target.sheet);
  }, [walls, wallKey, sheet, elevSheets]);
  const turn = (step: number) => {
    if (wallAt >= 0) { openWall(wallAt + step); return; }
    if (tab && at >= 0) {
      const next = tab.pages[at + step];
      if (next !== undefined) curtain.go(() => openSheet(next));
    }
  };

  // PageUp / PageDown go to the neighbouring page if the sheet has several
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
  const tabBar = useUnderline<HTMLElement>(`${info ? "info" : estimate ? "estimate" : tab?.pages[0] ?? "-"}|${tabs.length}|${t("overview.tab")}|${!!openEstimate}`);
  // Wiring variant as a line in the sheet side panel: "По группам проекта · По потолку · Через коробки"
  const activeVariant = variants ? parseKey(variants.active) : null;
  const variantLabel = activeVariant
    ? [t(`wizard.steps.breakers.options.${breakersOf(activeVariant.mode)}.name`), t(`variant.routes.${activeVariant.route}`), t(`variant.distributions.${activeSummary(variants!)?.distribution ?? "boxes"}`)].join(" · ")
    : null;
  const warn = project?.stale
    ? t("app.stale", { name: project.name })
    : project && !project.report ? t("app.notBuilt", { name: project.name }) : null;

  // While a project or sheet is loading: a preloader over the drawing (the previous sheet shows under it)
  const loading = !!current && !error && !source && (!project || (!!project.artifact && loaded !== sheet));
  // Between drawings: fade to the loading mark and back (shared/curtain.ts)
  const curtain = useCurtain(loading);

  // Download: sheet PNG (the whole sheet, at most A3 150 dpi) and the project DXF. A drawing with
  // options puts it in their first row, any other screen gets a row of its own
  const download = project && current && !estimate && !info && (
    <DownloadMenu
      onPng={page && !source && !loading ? () => downloadSheetPng(page, `${project.name}-${page.name}.png`) : null}
      dxf={project.dxf ? { href: `${base(current)}/out/${enc(project.dxf)}`, name: project.dxf } : null}
      withDxf={mode === "engineering"} />
  );
  let downloadInStage = false;
  let main: React.ReactNode;
  if (!current) main = <div className={ui.empty}>{t("app.chooseProject")}</div>;
  else if (error) main = <div className={ui.error}>{error}</div>;
  else if (source && project) main = <SourceView project={project} file={source} onBack={() => setSource(null)} />;
  else if (project && !project.artifact) main = <div className={ui.empty}>{t("app.noArtifact")}</div>;
  else if (info && project) {
    main = <OverviewStage overview={overview} variants={variants} project={project} openQuestions={openQs}
                          canChoose={project.can?.choose_variant ?? true} refreshing={refreshing || choosing}
                          onEstimate={openEstimate} onDrawer={(k) => { setDrawer(k); setClosing(false); }}
                          onWizard={setup?.total ? () => openWizard() : undefined} setup={setup ?? undefined} />;
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
    const built = (f: string) => (project.files.includes(f) ? `${base(current)}/out/${f}` : null);
    main = <PanelStage ref={stage} page={page} panel={page.panel} language={overview?.language}
                       stickersPdf={(colored, short) => built(stickersPdf(colored, short))}
                       mode={panelMode} onMode={setPanelMode} reserve={overview?.panel?.reserve}
                       reserveEditable={project.can?.answer === true && !!project.report?.questions.some((q) => q.id === "panel_reserve")}
                       busy={answering || refreshing}
                       onReserve={async (groups) => { await answerQuestion("panel_reserve", groups); }} />;
  } else if (page && project && !page.items?.length) {
    main = <div className={ui.error}>{t("app.nothingToDraw", { name: page.name })}</div>;
  } else if (page && project && wall?.data && elevSheets.includes(loaded ?? -1)) {
    main = <ElevationStage ref={stage} elevation={wall.data} withMap={!!scene} download={download} />;
    downloadInStage = true;
  } else if (page && project && drawing) {
    main = <SheetStage ref={stage} onStage={openStage} page={wallPage ?? page} drawing={drawing} project={project.name} language={overview?.language}
                       editable={project.can?.edit_wiring ?? true} download={download} onWall={toWall}
                       onSaved={saved} onBusy={setSaving} onBanner={(b) => setBanners([b])} />;
    downloadInStage = true;
  }
  if (page && project && main) main = <Boundary key={`${current}/${drawn.length > 1 ? "drawing" : loaded}/${shown}`}>{main}</Boundary>;

  // The studio settings are the studio's: login off, a firm account or the debug guest (reads)
  const openStudio = account === null || account.plan === "pro" || account.visitor
    ? () => { location.hash = studioHash("profile"); }
    : undefined;
  const settings = <Settings account={account} theme={theme} onTheme={(th) => { remember("theme", th); setTheme(th); }}
                             mode={mode} onMode={(m) => { rememberMode(m); setMode(m); }} onStudio={openStudio} />;

  return (
    <div className={css.app}>
      <AlphaNotice />
      {(choosing || saving) && <RebuildModal />}
      {wizard && project && (
        <Wizard key={current} start={wizardStart} project={project} variants={variants} ceiling={overview?.ceiling ?? null} scene={scene}
                reserve={overview?.panel?.reserve ?? null} master={overview?.panel?.master ?? null} onApply={applyWizard} onClose={() => setWizard(false)}
                onQuestions={() => { setWizard(false); setDrawer("questions"); setClosing(false); }} />
      )}
      {studio && (
        <Studio account={account} section={studio} onSection={(s) => { location.hash = studioHash(s); }}
                onBack={() => { location.hash = outside.current; }} />
      )}
      {!current && !studio && <Welcome list={list} onOpen={(name) => { location.hash = encodeURIComponent(name); }} settings={settings} />}
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
            {list.find((p) => isProject(p, current))?.title ?? current ?? t("app.projects")}
          </span>
        </button>
        {/* Sheet tabs: the active one is underlined, the line slides to the next (shared/underline.ts) */}
        <nav ref={tabBar.ref} className={css.sheets} aria-label={t("app.sheets")}>
          {/* Every built project has this tab: a build without the overview (old code) shows a hint to rebuild */}
          {project?.artifact && pages.length > 0 && (
            <button aria-current={info ? "page" : undefined} onClick={() => { if (!info) curtain.go(openInfo); }}>{t("overview.tab")}</button>
          )}
          {tabs.map((tb) => (
            <button key={tb.pages[0]} aria-current={tb === tab ? "page" : undefined}
                    title={tb.pages.length > 1 && !tb.views ? t("app.pages", { n: tb.pages.length }) : undefined}
                    onClick={() => {
                      const walls = elevSheets.includes(tb.pages[0]);
                      if (tb === tab && !info && !estimate) { openSheet(tabTarget(tb)); if (walls) setAllWalls(true); return; }
                      curtain.go(() => { if (openSheet(tabTarget(tb)) && walls) setAllWalls(true); });
                    }}>{tb.stage ? label("stage", tb.stage) : tb.name}</button>
          ))}
          {openEstimate && (
            <button aria-current={estimate ? "page" : undefined} onClick={() => { if (!estimate) curtain.go(openEstimate); }}>{t("estimate.tab")}</button>
          )}
          <span className={css.underline} style={tabBar.style} aria-hidden="true" />
        </nav>
        <button className={css.more} aria-label={t("app.more")} aria-expanded={more} onClick={() => setMore(!more)}>⋯</button>
        {/* On a phone: the "⋯" menu; choosing an action closes it */}
        <div className={cx(css.actions, more && css.open)} onClick={() => setMore(false)}>
          {project && (
            <div className={ui.segmented} aria-label={t("app.project")}>
              {drawerTabs.map((k) => {
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
        {/* Without a project the welcome screen covers the header and has its own gear */}
        {current && settings}
      </header>
      <div className={css.banners}>
        {outdated && (
          <div className={css.banner}>
            {t("app.newVersion", { brand: BRAND })}{" "}
            <button className={css.pill} onClick={() => location.reload()}>{t("common.refresh")}</button>
          </div>
        )}
        {/* Not built, YAML changed: a terminal command for the engineer, not for the simple mode */}
        {warn && mode === "engineering" && <div className={css.banner}>{warn}</div>}
        {banners.map((b) => <div key={b} className={css.banner}>{b}</div>)}
      </div>
      <main id="stage" className={css.stage}>
        {main}
        {download && !downloadInStage && <div className={ui.options}><div className={ui.optionsRow}>{download}</div></div>}
        {curtain.phase !== "idle" && (
          <div className={css.curtain} data-phase={curtain.phase} role="status" aria-live="polite">
            <MarkLoader />
          </div>
        )}
        {loading && !info && curtain.phase === "idle" && (
          <div className={css.loader} role="status" aria-live="polite">
            <MarkLoader />
            <span className="small muted">{project ? t("app.loadingSheet") : t("app.loadingProject")}</span>
          </div>
        )}
        {wall && page && !loading && !info && !estimate && !source ? (
          <>
            {/* Elevations: one page is one wall, the name opens a list of all walls; bottom left shows where it is in the flat */}
            {allWalls ? (
              <WallGrid walls={walls} pages={elevs} at={wallAt} onClose={closeAllWalls}
                        onPick={(index) => { setAllWalls(false); openWall(index); }} />
            ) : (
              <>
                <WallPager walls={walls} at={wallAt} onTurn={turn} onPick={openWall} onAll={() => setAllWalls(true)} />
                {scene && <WallMap scene={scene} elevation={wall.key} title={wall.title} face={wall.data?.face} />}
              </>
            )}
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
                 views={views} view={shownView} onView={pickView}
                 wall={!source && !loading ? wall?.data ?? null : null} onWiring={mode === "engineering" ? toWiring : undefined}
                 layers={mode === "engineering"}
                 variant={variantLabel ? { label: variantLabel, onOpen: openInfo } : null}
                 summary={info && !source ? <OverviewSummary setup={setup} questions={project?.report?.questions ?? []} refreshing={refreshing || choosing}
                                                             onWizard={setup?.total ? openWizard : undefined}
                                                             onDrawer={(k) => { setDrawer(k); setClosing(false); }} /> : undefined}>
        {drawer && project && (
          <Drawer tab={drawer} project={project} shownSource={source} onSource={showSource}
                  busy={answering || refreshing} onAnswer={answerQuestion} onReview={reviewQuestion}
                  stages={pages.flatMap((pg) => pg.stage ?? []).filter((st) => stageShown(mode, st))} onShow={showQuestion} memory={questionsMemory}
                  closing={closing} onClose={closeDrawer} onClosed={drawerClosed} />
        )}
      </SidePanel>
    </div>
  );
}

// Where the project was open in this browser: a sheet, the "Estimate" tab or "Overview" (place:<project>)
function savedPlace(name: string): { sheet: number; estimate: boolean; info: boolean } | null {
  try {
    const v = JSON.parse(remembered(`place:${name}`) || "null") as { sheet?: unknown; estimate?: unknown; info?: unknown } | null;
    return v && typeof v.sheet === "number" ? { sheet: v.sheet, estimate: v.estimate === true, info: v.info === true } : null;
  } catch {
    return null;
  }
}
